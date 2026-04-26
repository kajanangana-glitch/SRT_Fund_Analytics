#!/usr/bin/env python
# coding: utf-8

# In[1]:


import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
 
# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(page_title="SRT Fund Analyser", layout="wide", page_icon="📊")
 
# ══════════════════════════════════════════════════════════════════════════════
# LOAD DATA
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data
def load_data():
    df = pd.read_excel("/Users/kaj/Downloads/SRT_Obligor_Data.xlsx", header=1)
    df = df[df["Deal ID"].notna()].copy()
    df["Deal Date"]     = pd.to_datetime(df["Deal Date"])
    df["Maturity Date"] = pd.to_datetime(df["Maturity Date"])
    df["EL_pct"]        = df["PD"] * df["LGD"]
    df["EL_eur_m"]      = df["EL_pct"] * df["Exposure (€m)"]
    df["EL_bps"]        = df["EL_pct"] * 10000
    return df
 
df = load_data()


# In[2]:


# SIDEBAR — MACRO INPUTS
# ══════════════════════════════════════════════════════════════════════════════
st.sidebar.title("SRT Fund Analyser")
st.sidebar.markdown("---")
st.sidebar.subheader("Macro Inputs")
 


pd_multiplier  = st.sidebar.slider("PD Multiplier",      1.0, 5.0,  1.0, 0.1)
lgd_multiplier = st.sidebar.slider("LGD Multiplier",     1.0, 1.6,  1.0, 0.05)
benchmark_rate = st.sidebar.slider("Benchmark Rate (%)", 0.0, 8.0,  3.5, 0.1)
gdp_growth     = st.sidebar.slider("GDP Growth (%)",    -5.0, 6.0,  2.0, 0.1)
inflation      = st.sidebar.slider("Inflation (%)",      0.0, 12.0, 2.5, 0.1)
 
st.sidebar.markdown("---")
 
# Combined PD multiplier
gdp_adj          = max(0, -gdp_growth / 100) * 0.20
rate_adj         = max(0, benchmark_rate / 100 - 0.05) * 0.2
combined_pd_mult = pd_multiplier * (1 + gdp_adj) * (1 + rate_adj)
 

st.sidebar.markdown(f"**Combined PD Multiplier:** `{combined_pd_mult:.2f}x`")
 


# In[5]:


# APPLY STRESS & ROLL UP TO DEAL LEVEL
# ══════════════════════════════════════════════════════════════════════════════
 
# Obligor level stress
df["stressed_pd"]       = np.minimum(df["PD"]  * combined_pd_mult, 0.99)
df["stressed_lgd"]      = np.minimum(df["LGD"] * lgd_multiplier,   0.99)
df["stressed_el_pct"]   = df["stressed_pd"] * df["stressed_lgd"]
df["stressed_el_eur_m"] = df["stressed_el_pct"] * df["Exposure (€m)"]
 
# Roll up to deal level
deal = df.groupby("Deal ID").agg(
    bank_name       = ("Bank Name",             "first"),
    asset_class     = ("Asset Class",           "first"),
    geography       = ("Geography",             "first"),
    deal_date       = ("Deal Date",             "first"),
    maturity_date   = ("Maturity Date",         "first"),
    tranche_type    = ("Tranche Type",          "first"),
    attachment      = ("Attachment Point",      "first"),
    detachment      = ("Detachment Point",      "first"),
    tranche_eur_m   = ("Tranche Notional (€m)", "first"),
    spread_bps      = ("Spread (bps)",          "first"),
    orig_quality    = ("Originator Quality",    "first"),
    orig_rating     = ("Originator Rating",     "first"),
    servicer_risk   = ("Servicer Risk",         "first"),
    num_obligors    = ("Obligor ID",            "count"),
    pool_size_eur_m = ("Exposure (€m)",         "sum"),
    total_el_eur_m  = ("EL_eur_m",              "sum"),
).reset_index()
 
# Weighted averages
deal["wa_pd"] = df.groupby("Deal ID").apply(
    lambda x: np.average(x["PD"], weights=x["Exposure (€m)"])
).values
deal["wa_lgd"] = df.groupby("Deal ID").apply(
    lambda x: np.average(x["LGD"], weights=x["Exposure (€m)"])
).values
deal["stressed_wa_pd"] = df.groupby("Deal ID").apply(
    lambda x: np.average(x["stressed_pd"], weights=x["Exposure (€m)"])
).values
deal["stressed_wa_lgd"] = df.groupby("Deal ID").apply(
    lambda x: np.average(x["stressed_lgd"], weights=x["Exposure (€m)"])
).values
 
# Base metrics
deal["wa_el_pct"]             = deal["wa_pd"] * deal["wa_lgd"]
deal["wa_el_bps"]             = deal["wa_el_pct"] * 10000
deal["net_carry_bps"]         = deal["spread_bps"] - deal["wa_el_bps"]
deal["distance_to_attach_pct"]= deal["attachment"] - deal["wa_el_pct"]
deal["break_even_pd"]         = deal["attachment"] / deal["wa_lgd"]
deal["safety_multiple"]       = deal["attachment"] / deal["wa_el_pct"]

 
# Stressed metrics
deal["stressed_el_pct"]           = deal["stressed_wa_pd"] * deal["stressed_wa_lgd"]
deal["stressed_el_bps"]           = deal["stressed_el_pct"] * 10000
deal["stressed_net_carry_bps"]    = deal["spread_bps"] - deal["stressed_el_bps"]
deal["stressed_distance_to_attach"]= deal["attachment"] - deal["stressed_el_pct"]
deal["stressed_safety_multiple"]  = deal["attachment"] / deal["stressed_el_pct"].replace(0, np.nan)

 
# Live gross yield
deal["live_gross_yield"] = benchmark_rate / 100 + deal["spread_bps"] / 10000
 
# Tranche status
def tranche_status(row):
    dist  = row["stressed_distance_to_attach"]
    thick = row["detachment"] - row["attachment"]
    if dist > thick * 0.4:   return "Safe"
    elif dist > 0:            return "Watch"
    elif row["stressed_el_pct"] < row["detachment"]: return "At Risk"
    else:                     return "Breached"
 
deal["status"] = deal.apply(tranche_status, axis=1)
 
# Spread adequacy
required_buffer_bps           = 200
deal["fair_value_spread_bps"] = deal["stressed_el_bps"] + required_buffer_bps
deal["spread_adequacy_bps"]   = deal["spread_bps"] - deal["fair_value_spread_bps"]
deal["adequacy_flag"]         = deal["spread_adequacy_bps"].apply(
    lambda x: "OK" if x > 50 else "WATCH" if x > 0 else "TIGHT" if x > -50 else "INADEQUATE"
)
 
# Maturity
today                    = pd.Timestamp.today()
deal["days_to_maturity"] = (deal["maturity_date"] - today).dt.days
deal["years_to_maturity"]= deal["days_to_maturity"] / 365
deal["maturity_year"]    = deal["maturity_date"].dt.year
deal["vintage_year"]     = deal["deal_date"].dt.year
deal["maturity_flag"]    = deal["days_to_maturity"].apply(
    lambda x: "URGENT" if x < 180 else "WATCH" if x < 365 else "MONITOR" if x < 730 else "OK"
)
 
# Fund summary
w = deal["tranche_eur_m"]
fund = {
    "total_deals":          len(deal),
    "total_banks":          deal["bank_name"].nunique(),
    "total_obligors":       len(df),
    "total_pool_eur_m":     round(deal["pool_size_eur_m"].sum(), 1),
    "total_notional_eur_m": round(w.sum(), 1),
    "wa_spread_bps":        round(np.average(deal["spread_bps"],             weights=w), 1),
    "wa_gross_yield":       round(np.average(deal["live_gross_yield"],        weights=w), 4),
    "wa_pd":                round(np.average(deal["wa_pd"],                   weights=w), 4),
    "wa_lgd":               round(np.average(deal["wa_lgd"],                  weights=w), 4),
    "wa_el_bps":            round(np.average(deal["wa_el_bps"],               weights=w), 1),
    "wa_stressed_el_bps":   round(np.average(deal["stressed_el_bps"],         weights=w), 1),
    "wa_net_carry_bps":     round(np.average(deal["net_carry_bps"],           weights=w), 1),
    "wa_stressed_carry":    round(np.average(deal["stressed_net_carry_bps"],  weights=w), 1),
    "wa_safety_multiple":   round(np.average(deal["safety_multiple"],         weights=w), 2),
}


# In[6]:


# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Fund Summary",
    "🔬 Deal Analysis",
    "📉 Concentration",
    "⚠️ Spread Adequacy"
])
 


# In[ ]:





# In[8]:


# TAB 1 — FUND SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
 
    st.subheader("Fund Overview")
 
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total Deals",     fund["total_deals"])
    k2.metric("Total Banks",     fund["total_banks"])
    k3.metric("Total Obligors",  f"{fund['total_obligors']:,}")
    k4.metric("Total Notional",  f"€{fund['total_notional_eur_m']}m")
    k5.metric("WA Spread",       f"{fund['wa_spread_bps']}bps")
    k6.metric("WA Gross Yield",  f"{fund['wa_gross_yield']:.2%}")
 
    st.markdown("---")
 
    k7, k8, k9, k10, k11 = st.columns(5)
    k7.metric("WA Expected Loss",   f"{fund['wa_el_bps']}bps",
              delta=f"Stressed: {fund['wa_stressed_el_bps']}bps", delta_color="inverse")
    k8.metric("WA Net Carry",       f"{fund['wa_net_carry_bps']}bps",
              delta=f"Stressed: {fund['wa_stressed_carry']}bps",  delta_color="inverse")
    k9.metric("WA Safety Multiple", f"{fund['wa_safety_multiple']}x")
    k10.metric("WA PD",             f"{fund['wa_pd']:.3%}")
    k11.metric("WA PD",             f"{fund['wa_lgd']:.2%}")
 
    st.markdown("---")
    st.subheader("Tranche Status Under Current Macro Stress")
 
    status_counts = deal["status"].value_counts()
    all_statuses  = ["Safe", "Watch", "At Risk", "Breached"]
    colours       = ["#3FB950", "#D29922", "#F85149", "#FF0000"]
 
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure(go.Pie(
            labels=all_statuses,
            values=[status_counts.get(s, 0) for s in all_statuses],
            hole=0.6, marker=dict(colors=colours), textinfo="label+value"
        ))
        fig.update_layout(height=300, showlegend=False, margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)
 
    with c2:
        status_df = pd.DataFrame({
            "Status":    all_statuses,
            "Deals":     [status_counts.get(s, 0) for s in all_statuses],
            "Notional":  [f"€{deal[deal['status']==s]['tranche_eur_m'].sum():.1f}m" for s in all_statuses],
            "% of Fund": [f"{deal[deal['status']==s]['tranche_eur_m'].sum() / fund['total_notional_eur_m']:.1%}" for s in all_statuses],
        })
 
        def colour_status(val):
            m = {"Safe": "background-color:#1a3a2a;color:#3FB950",
                 "Watch": "background-color:#3a2e1a;color:#D29922",
                 "At Risk": "background-color:#3a1f1a;color:#F85149",
                 "Breached": "background-color:#5a0a0a;color:#FF0000"}
            return m.get(val, "")
 
        st.dataframe(status_df.style.map(colour_status, subset=["Status"]),
                     use_container_width=True, hide_index=True, height=200)
 
    st.markdown("---")
    st.subheader("Base vs Stressed — All Deals")
 
    compare = deal[["Deal ID","bank_name","asset_class",
                    "wa_el_bps","stressed_el_bps",
                    "net_carry_bps","stressed_net_carry_bps",
                    "distance_to_attach_pct","stressed_distance_to_attach",
                    "safety_multiple","stressed_safety_multiple","status"]].copy()
    compare.columns = ["Deal ID","Bank","Asset Class",
                       "Base EL (bps)","Stressed EL (bps)", 
                       "Base Carry (bps)","Stressed Carry (bps)",
                       "Base Distance","Stressed Distance",
                       "Base Safety","Stressed Safety","Status"]
 
    st.dataframe(
        compare.style
            .format({"Base EL (bps)":"{:.1f}","Stressed EL (bps)":"{:.1f}",
                     "Base Carry (bps)":"{:.1f}","Stressed Carry (bps)":"{:.1f}",
                     "Base Distance":"{:.3%}","Stressed Distance":"{:.3%}",
                     "Base Safety":"{:.1f}x","Stressed Safety":"{:.1f}x"})
            .map(colour_status, subset=["Status"]),
        use_container_width=True, hide_index=True, height=450
    )


# In[9]:


# TAB 2 — DEAL ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
 
    st.subheader("Deal Analysis")
 
    f1, f2, f3 = st.columns(3)
    with f1:
        selected_ac = st.selectbox("Asset Class",
            ["All"] + sorted(deal["asset_class"].unique().tolist()), key="ac")
    with f2:
        selected_geo = st.selectbox("Geography",
            ["All"] + sorted(deal["geography"].unique().tolist()), key="geo")
    with f3:
        selected_status = st.selectbox("Status",
            ["All", "Safe", "Watch", "At Risk", "Breached"], key="status")
 
    deal_f = deal.copy()
    if selected_ac     != "All": deal_f = deal_f[deal_f["asset_class"] == selected_ac]
    if selected_geo    != "All": deal_f = deal_f[deal_f["geography"]   == selected_geo]
    if selected_status != "All": deal_f = deal_f[deal_f["status"]      == selected_status]
 
    st.markdown(f"Showing **{len(deal_f)}** deals")
    st.markdown("---")
 
    # Scatter — spread vs stressed EL
    st.subheader("Spread vs Stressed Expected Loss")
    fig1 = px.scatter(
        deal_f, x="stressed_el_bps", y="spread_bps",
        color="status",
        color_discrete_map={"Safe":"#3FB950","Watch":"#D29922","At Risk":"#F85149","Breached":"#FF0000"},
        size="tranche_eur_m",
        hover_data=["bank_name","asset_class","tranche_eur_m"],
        labels={"stressed_el_bps":"Stressed EL (bps)","spread_bps":"Spread (bps)"},
    )
    max_el = deal_f["stressed_el_bps"].max() * 1.1
    fig1.add_trace(go.Scatter(x=[0, max_el], y=[0, max_el], mode="lines",
                              name="Break-even", line=dict(color="#D29922", dash="dash")))
    fig1.update_layout(height=400)
    st.plotly_chart(fig1, use_container_width=True)
 
    st.markdown("---")
 
    # Distance to attachment
    st.subheader("Distance to Attachment — Base vs Stressed")
    ds = deal_f.sort_values("stressed_distance_to_attach")
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(name="Base", x=ds["bank_name"], y=ds["distance_to_attach_pct"],
                          marker_color="#58A6FF", opacity=1))
    fig2.add_trace(go.Bar(name="Stressed", x=ds["bank_name"], y=ds["stressed_distance_to_attach"],
                          marker_color=["#3FB950" if v > 0.01 else "#D29922" if v > 0 else "#F85149"
                                        for v in ds["stressed_distance_to_attach"]]))
    
    fig2.update_layout(barmode="group", height=380, xaxis_tickangle=-35,
                       yaxis_tickformat=".1%", legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig2, use_container_width=True)
 
    st.markdown("---")
 
    # Full deal table
    st.subheader("Full Deal Table")
    table = deal_f[["Deal ID","bank_name","asset_class","geography",
                     "vintage_year","maturity_year","num_obligors",
                     "pool_size_eur_m","tranche_eur_m","attachment","detachment",
                     "spread_bps","wa_pd","wa_lgd","wa_el_bps","stressed_el_bps",
                     "net_carry_bps","stressed_net_carry_bps",
                     "break_even_pd","safety_multiple","status","maturity_flag"]].copy()
    table.columns = ["Deal ID","Bank","Asset Class","Geography",
                     "Vintage","Matures","Obligors","Pool (€m)","Tranche (€m)",
                     "Attach","Detach","Spread (bps)","WA PD","WA LGD",
                     "Base EL (bps)","Stressed EL (bps)",
                     "Base Carry (bps)","Stressed Carry (bps)",
                     "Break-even PD","Safety Multiple","Status","Maturity Flag"]
 
    def colour_maturity(val):
        m = {"URGENT":"background-color:#5a0a0a;color:#FF0000",
             "WATCH":"background-color:#3a2e1a;color:#D29922",
             "MONITOR":"background-color:#1a2e3a;color:#58A6FF",
             "OK":"background-color:#1a3a2a;color:#3FB950"}
        return m.get(val, "")
 
    st.dataframe(
        table.style
            .format({"Pool (€m)":"{:.1f}","Tranche (€m)":"{:.1f}",
                     "Attach":"{:.1%}","Detach":"{:.1%}",
                     "WA PD":"{:.3%}","WA LGD":"{:.2%}",
                     "Base EL (bps)":"{:.1f}","Stressed EL (bps)":"{:.1f}",
                     "Base Carry (bps)":"{:.1f}","Stressed Carry (bps)":"{:.1f}",
                     "Break-even PD":"{:.2%}","Safety Multiple":"{:.1f}x"})
            .map(colour_status,   subset=["Status"])
            .map(colour_maturity, subset=["Maturity Flag"]),
        use_container_width=True, hide_index=True, height=450
    )
 


# In[10]:


# TAB 3 — CONCENTRATION
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
 
    st.subheader("Concentration Analysis")
 
    total_fund_exposure = df["Exposure (€m)"].sum()
    total_notional      = deal["tranche_eur_m"].sum()
 
    # Bank concentration
    st.subheader("Bank / Originator Concentration")
    bank_conc = deal.groupby("bank_name").agg(
        num_deals=("Deal ID","count"), total_notional=("tranche_eur_m","sum"),
        avg_spread=("spread_bps","mean")
    ).reset_index()
    bank_conc["fund_weight"] = bank_conc["total_notional"] / total_notional
    bank_conc["flag"]        = bank_conc["fund_weight"].apply(
        lambda x: "HIGH" if x > 0.20 else "WATCH" if x > 0.10 else "OK")
    bank_conc = bank_conc.sort_values("fund_weight", ascending=False)
 
    b1, b2 = st.columns(2)
    with b1:
        fig_b = px.bar(bank_conc, x="fund_weight", y="bank_name", orientation="h",
                       color="flag", color_discrete_map={"HIGH":"#F85149","WATCH":"#D29922","OK":"#3FB950"},
                       labels={"fund_weight":"% of Fund","bank_name":"Bank"})
        fig_b.add_vline(x=0.20, line_color="#F85149", line_dash="dash",
                        annotation_text="20% threshold", annotation_font_color="#F85149")
        fig_b.update_layout(height=420, xaxis_tickformat=".0%", showlegend=False)
        st.plotly_chart(fig_b, use_container_width=True)
 
    with b2:
        disp = bank_conc.copy()
        disp["fund_weight"]    = disp["fund_weight"].map("{:.2%}".format)
        disp["total_notional"] = disp["total_notional"].map("€{:.1f}m".format)
        disp["avg_spread"]     = disp["avg_spread"].map("{:.0f}bps".format)
        disp.columns = ["Bank","Deals","Notional","Avg Spread","Weight","Flag"]
 
        def colour_flag(val):
            m = {"HIGH":"background-color:#3a1f1a;color:#F85149",
                 "WATCH":"background-color:#3a2e1a;color:#D29922",
                 "OK":"background-color:#1a3a2a;color:#3FB950"}
            return m.get(val, "")
 
        st.dataframe(disp.style.map(colour_flag, subset=["Flag"]),
                     use_container_width=True, hide_index=True, height=420)
 
    st.markdown("---")
 
    # Sector concentration
    st.subheader("Sector Concentration")
    sector_conc = df.groupby("Sector")["Exposure (€m)"].sum().reset_index()
    sector_conc.columns = ["Sector","total_exposure"]
    sector_conc["fund_weight"] = sector_conc["total_exposure"] / total_fund_exposure
    sector_conc["flag"]        = sector_conc["fund_weight"].apply(
        lambda x: "HIGH" if x > 0.20 else "WATCH" if x > 0.10 else "OK")
    sector_conc = sector_conc.sort_values("fund_weight", ascending=False)
 
    s1,= st.columns(1)
    with s1:
        fig_s = px.bar(sector_conc, x="fund_weight", y="Sector", orientation="h",
                       color="flag", color_discrete_map={"HIGH":"#F85149","WATCH":"#D29922","OK":"#3FB950"},
                       labels={"fund_weight":"% of Fund"})
        fig_s.add_vline(x=0.20, line_color="#F85149", line_dash="dash",
                        annotation_text="20% threshold", annotation_font_color="#F85149")
        fig_s.update_layout(height=500, xaxis_tickformat=".0%", showlegend=False)
        st.plotly_chart(fig_s, use_container_width=True)
 

 
    st.markdown("---")
 
    # Geographic concentration
    st.subheader("Geographic Concentration")
    geo_conc = df.groupby("Country")["Exposure (€m)"].sum().reset_index()
    geo_conc.columns = ["Country","total_exposure"]
    geo_conc["fund_weight"] = geo_conc["total_exposure"] / total_fund_exposure
    geo_conc["flag"]        = geo_conc["fund_weight"].apply(
        lambda x: "HIGH" if x > 0.20 else "WATCH" if x > 0.10 else "OK")
    geo_conc = geo_conc.sort_values("fund_weight", ascending=False)
 
    g1, g2 = st.columns(2)
    with g1:
        fig_g = px.bar(geo_conc.head(15), x="fund_weight", y="Country", orientation="h",
                       color="flag", color_discrete_map={"HIGH":"#F85149","WATCH":"#D29922","OK":"#3FB950"},
                       labels={"fund_weight":"% of Fund"})
        fig_g.add_vline(x=0.20, line_color="#F85149", line_dash="dash",
                        annotation_text="20% threshold", annotation_font_color="#F85149")
        fig_g.update_layout(height=500, xaxis_tickformat=".0%", showlegend=False)
        st.plotly_chart(fig_g, use_container_width=True)
 
    with g2:
        ac_conc = df.groupby("Asset Class")["Exposure (€m)"].sum().reset_index()
        ac_conc.columns = ["Asset Class","total_exposure"]
        ac_conc["fund_weight"] = ac_conc["total_exposure"] / total_fund_exposure
        fig_ac = px.pie(ac_conc, values="fund_weight", names="Asset Class", title="Asset Class Mix")
        fig_ac.update_layout(height=500)
        st.plotly_chart(fig_ac, use_container_width=True)
 
    st.markdown("---")
 
    # Maturity wall
    st.subheader("Maturity Wall")
    mat_wall = deal.groupby("maturity_year").agg(
        num_deals=("Deal ID","count"), total_notional=("tranche_eur_m","sum"),
        avg_spread=("spread_bps","mean")
    ).reset_index()
    mat_wall["pct_of_fund"] = mat_wall["total_notional"] / total_notional
 
    fig_m = px.bar(mat_wall, x="maturity_year", y="total_notional",
                   text="num_deals", color="pct_of_fund",
                   color_continuous_scale=["#3FB950","#D29922","#F85149"],
                   labels={"maturity_year":"Year","total_notional":"Notional (€m)","pct_of_fund":"% of Fund"})
    fig_m.update_traces(texttemplate="%{text} deals", textposition="outside")
    fig_m.update_layout(height=350, xaxis=dict(dtick=1))
    st.plotly_chart(fig_m, use_container_width=True)
 


# In[11]:


# TAB 4 — SPREAD ADEQUACY
# ══════════════════════════════════════════════════════════════════════════════
with tab4:
 
    st.subheader("Spread Adequacy Analysis")
 
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("WA Spread",           f"{fund['wa_spread_bps']}bps")
    a2.metric("WA Stressed EL",      f"{fund['wa_stressed_el_bps']}bps")
    a3.metric("WA Fair Value Spread", f"{round(np.average(deal['fair_value_spread_bps'], weights=w), 1)}bps")
    wa_adeq = round(np.average(deal["spread_adequacy_bps"], weights=w), 1)
    a4.metric("WA Spread Adequacy",  f"{wa_adeq}bps")
 
    st.markdown("---")
 
    flag_counts = deal["adequacy_flag"].value_counts()
    f1, f2, f3, f4 = st.columns(4)
    for col, flag in zip([f1,f2,f3,f4], ["OK","WATCH","TIGHT","INADEQUATE"]):
        col.metric(flag, f"{flag_counts.get(flag, 0)} deals")
 
    st.markdown("---")
 
  
    # Vintage analysis
    st.subheader("Vintage Analysis — Are Older Deals Still Fairly Priced?")
    vintage = deal.groupby("vintage_year").agg(
        num_deals=("Deal ID","count"),
        avg_spread=("spread_bps","mean"),
        avg_stressed_el=("stressed_el_bps","mean"),
        avg_adequacy=("spread_adequacy_bps","mean"),
    ).reset_index()
 
    v1,= st.columns(1)
    with v1:
        fig_v1 = go.Figure()
        fig_v1.add_trace(go.Bar(name="Avg Spread", x=vintage["vintage_year"],
                                y=vintage["avg_spread"], marker_color="#58A6FF", opacity=0.7))
        fig_v1.add_trace(go.Bar(name="Avg Stressed EL", x=vintage["vintage_year"],
                                y=vintage["avg_stressed_el"], marker_color="#F85149", opacity=0.7))
        fig_v1.update_layout(barmode="group", height=320, xaxis=dict(dtick=1),
                             yaxis_title="bps", legend=dict(orientation="h", y=1.1),
                             title="Avg Spread vs Stressed EL by Vintage")
        st.plotly_chart(fig_v1, use_container_width=True)
 
  
 
    st.markdown("---")
 
    # Full adequacy table
    st.subheader("Deal Level Spread Adequacy")
    adeq = deal[["Deal ID","bank_name","asset_class","vintage_year",
                 "spread_bps","stressed_el_bps","fair_value_spread_bps",
                 "spread_adequacy_bps","adequacy_flag"]].copy()
    adeq.columns = ["Deal ID","Bank","Asset Class","Vintage",
                    "Spread (bps)","Stressed EL (bps)","Fair Value Spread (bps)",
                    "Adequacy (bps)","Flag"]
    adeq = adeq.sort_values("Adequacy (bps)").reset_index(drop=True)
 
    def colour_adeq(val):
        m = {"OK":"background-color:#1a3a2a;color:#3FB950",
             "WATCH":"background-color:#3a2e1a;color:#D29922",
             "TIGHT":"background-color:#3a1f1a;color:#F85149",
             "INADEQUATE":"background-color:#5a0a0a;color:#FF0000"}
        return m.get(val, "")
 
    st.dataframe(
        adeq.style
            .format({"Spread (bps)":"{:.0f}","Stressed EL (bps)":"{:.1f}",
                     "Fair Value Spread (bps)":"{:.1f}","Adequacy (bps)":"{:.1f}"})
            .map(colour_adeq, subset=["Flag"])
            .background_gradient(subset=["Adequacy (bps)"], cmap="RdYlGn", vmin=-200, vmax=400),
        use_container_width=True, hide_index=True, height=450
    )
 


# In[ ]:





# In[ ]:




