import pandas as pd

def generaliser_age(age):
    if pd.isnull(age): return age
    age = int(age)
    if age < 30:
        return "20-29"
    elif age < 50:
        return "40-49"
    else:
        return "50+"

def verifier_k_anonymat(df, qids, k):
    groups = df.groupby(qids).size().reset_index(name='count')
    violators = groups[groups["count"] < k]
    est_k_anonyme = violators.empty
    return est_k_anonyme, groups, violators
