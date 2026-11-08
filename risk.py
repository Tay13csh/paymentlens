# PayGuard AI - Risk Analysis
# This program calculates transaction risk scores based on spending patterns.


# Day 1: Basic risk classification
# Initially, I used fixed transaction amounts to classify risk.
# However, this does not consider individual spending habits.

def check_risk(amount):
    if amount > 500:
        return "High Risk"
    elif amount > 100:
        return "Medium Risk"
    else:
        return "Low Risk"

print(check_risk(850))
print(check_risk(200))
print(check_risk(50))

assert check_risk(850) == "High Risk"
assert check_risk(200) == "Medium Risk"
assert check_risk(50) == "Low Risk"

#Day 2: Improved risk scoring
#Instead of fixed amounts, I implemented a transaction ratio based on transaction history.

def transaction_ratio(amount, average):
    return amount / average 

def calculate_score(amount, average):
    ratio = transaction_ratio(amount, average)
    if ratio >= 5:
        return 80
    elif ratio >= 2:
        return 50
    else:
        return 10

def risk_level(score):
    if score >= 80:
        return "High Risk"
    elif score >= 50:
        return "Medium Risk"
    else:
        return "Low Risk"

transaction = [40, 60, 80, 100, 120]
average = sum(transaction) / len(transaction)

print("Average Transaction Amount (CAD):", average)
print("Risk Score:", calculate_score(800, average))
print("Risk Level:", risk_level(calculate_score(800, average)))

#Day2 testing
# Day 2: Tests

# Test 1: Transaction Ratio
assert transaction_ratio(300, 20) == 15
assert transaction_ratio(600, 2000) == 0.3
assert transaction_ratio(100, 50) == 2
assert transaction_ratio(50, 100) == 0.5

# Test 2: Risk Score
assert calculate_score(300, 20) == 80
assert calculate_score(600, 2000) == 10
assert calculate_score(150, 50) == 50

# Test 3: Risk Level
assert risk_level(80) == "High Risk"
assert risk_level(50) == "Medium Risk"
assert risk_level(10) == "Low Risk"

print("All Day 2 tests passed!")
