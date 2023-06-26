##############################################################
# CLTV Prediction with BG-NBD ve Gamma-Gamma 
##############################################################

##############################################################
# 1. Data Preperation
##############################################################

import datetime as dt
from datetime import timedelta
import pandas as pd
import matplotlib.pyplot as plt
from lifetimes import BetaGeoFitter
from lifetimes import GammaGammaFitter
from lifetimes.plotting import plot_period_transactions

pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', 10)
pd.set_option('display.float_format', lambda x: '%.5f' % x)

def outlier_thresholds(dataframe, variable):
    quartile1 = dataframe[variable].quantile(0.01)
    quartile3 = dataframe[variable].quantile(0.99)
    interquantile_range = quartile3 - quartile1
    up_limit = quartile3 + 1.5 * interquantile_range
    low_limit = quartile1 - 1.5 * interquantile_range
    return low_limit, up_limit

def replace_with_thresholds(dataframe, variable):
    low_limit, up_limit = outlier_thresholds(dataframe, variable)
    # dataframe.loc[(dataframe[variable] < low_limit), variable] = low_limit
    dataframe.loc[(dataframe[variable] > up_limit), variable] = up_limit

def read_data():
    df =pd.read_excel("datasets/online_retail_II.xlsx", sheet_name="Year 2010-2011")
    return df

def get_info(df):
    print(df.describe([0.05, 0.25, 0.50, 0.75, 0.95, 0.99, 1]).T)

def prep_data(df):
    df.dropna(inplace=True)
    df = df[~df["Invoice"].str.contains("C", na=False)]
    df = df[df["Quantity"] > 0]
    replace_with_thresholds(df, "Quantity")
    replace_with_thresholds(df, "Price")
    df["TotalPrice"] = df["Price"] * df["Quantity"]
    # UK müşterilerini seçme
    df = df[df["Country"] == "United Kingdom"]
    return df

def get_analyse_date(df):
    max_date = df["InvoiceDate"].max()
    today_date = max_date + timedelta(days=2)
    #today_date = dt.datetime(2011, 12, 11)
    return today_date

df_ = read_data()
df = df_.copy()
df = prep_data(df)
today_date = get_analyse_date(df)

#############################################
# RFM Table
#############################################
# metrikleri oluşturma

def rfm_df():
    rfm = df.groupby('Customer ID').agg({'InvoiceDate': [lambda date: (date.max()-date.min()).days,
                                                        lambda date: (today_date-date.min()).days],
                                        'Invoice': lambda num: num.nunique(),
                                        'TotalPrice': lambda price: price.sum()})
    rfm.columns = rfm.columns.droplevel(0)

    # sütunları isimlendirme
    rfm.columns = ['recency_cltv_p', 'tenure', 'frequency', 'monetary']

    # monetary avg hesaplama --> Gamma Gamma modeli bu şekilde istiyor
    rfm["monetary"] = rfm["monetary"] / rfm["frequency"]

    rfm.rename(columns={"monetary": "monetary_avg"}, inplace=True)

    # recency ve tenure değişkenlerini haftalığa çevirme
    rfm["recency_weekly_p"] = rfm["recency_cltv_p"] / 7
    rfm["tenure_weekly_p"] = rfm["tenure"] / 7

    # kontroller
    rfm = rfm[rfm["monetary_avg"] > 0]
    rfm = rfm[rfm["frequency"] > 1]
    rfm["frequency"] = rfm["frequency"].astype(int)
    return rfm

rfm = rfm_df(df)

##############################################################
# 2. Creation of BG/NBD model
##############################################################

def fit_bgf(rfm):
    bgf = BetaGeoFitter(penalizer_coef=0.001)
    bgf.fit(rfm['frequency'],
            rfm['recency_weekly_p'],
            rfm['tenure_weekly_p'])
    return bgf

def pred_bgf(bgf,week=24,n_cust=10):
    # week/4 ay içinde en çok satın alma beklediğimiz n_cust müşteri kimdir?
    top_customers = bgf.conditional_expected_number_of_purchases_up_to_time(week,
                                                            rfm['frequency'],
                                                            rfm['recency_weekly_p'],
                                                            rfm['tenure_weekly_p']).sort_values(ascending=False)
    print(top_customers.head(n_cust))

def exp_sales(bgf,rfm,week=24):
    rfm["exp_sales_6_month"] = bgf.predict(week,
                                            rfm['frequency'],
                                            rfm['recency_weekly_p'],
                                            rfm['tenure_weekly_p'])

    rfm.sort_values("exp_sales_6_month", ascending=False).head(20)
    return rfm

def expected_transaction(bgf,rfm,week=24):
    # 6 Ayda Tüm Şirketin Beklenen Satış Sayısı Nedir?  952.4548865072431
    trasaction_count = bgf.predict(week,
                rfm['frequency'],
                rfm['recency_weekly_p'],
                rfm['tenure_weekly_p']).sum()
    print(f"Number of transaction in {week} week is: {trasaction_count}")

def eval_predictions(bgf):
    # Tahmin Sonuçlarının Değerlendirilmesi
    plot_period_transactions(bgf)
    plt.show()

bgf = fit_bgf(rfm)
pred_bgf(rfm,24,10)
rfm = exp_sales(bgf,rfm,24)
expected_transaction(bgf,rfm,24)
eval_predictions(bgf)

##############################################################
# 3. GAMMA-GAMMA modelinin kurulması
##############################################################
def fit_ggf(rfm):
    ggf = GammaGammaFitter(penalizer_coef=0.01)
    ggf.fit(rfm['frequency'], rfm['monetary_avg'])
    return ggf

def pred_ggf(ggf,rfm):
    ggf.conditional_expected_average_profit(rfm['frequency'],
                                            rfm['monetary_avg']).sort_values(ascending=False).head(10)

    rfm["expected_average_profit"] = ggf.conditional_expected_average_profit(rfm['frequency'],
                                                                            rfm['monetary_avg'])
    return rfm

ggf = fit_ggf(rfm)
rfm = pred_ggf(ggf,rfm)
print(rfm.sort_values("expected_average_profit", ascending=False).head(20))

##############################################################
# 4. BG-NBD ve GG modeli ile CLTV'nin hesaplanması.
##############################################################

def calculate_clv(bgf,ggf,rfm):
    cltv = ggf.customer_lifetime_value(bgf,
                                    rfm['frequency'],
                                    rfm['recency_weekly_p'],
                                    rfm['tenure_weekly_p'],
                                    rfm['monetary_avg'],
                                    time=6,
                                    freq="W",
                                    discount_rate=0.01)

    cltv = cltv.reset_index()
    cltv.sort_values(by="clv", ascending=False).head(50)
    rfm_cltv_final = rfm.merge(cltv, on="Customer ID", how="left")
    rfm_cltv_final.sort_values(by="clv", ascending=False).head()

    return rfm_cltv_final

rfm_cltv_final = calculate_clv(bgf,ggf,rfm)

print(rfm_cltv_final.head())
print(rfm_cltv_final.shape)