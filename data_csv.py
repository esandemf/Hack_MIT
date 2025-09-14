import pandas as pd
def load_schools():
    df = pd.read_csv("HACKMIT- School Database - Sheet1 (2).csv")   # relative path
    df["T1_population"] = df["Population"].astype(float)
    df["T1_Proportion"] = df["enrollment"].astype(int)
    return df

df = load_schools()