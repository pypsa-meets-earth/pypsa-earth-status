<!--
SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors

SPDX-License-Identifier: CC-BY-4.0
-->
# Detailed Validation Statistics

Detailed comparisons of active validation scenarios. Metrics are grouped by country and pillar.

## Australia (AU) — Scenario `AU_2021`

* **Model Year:** 2021
* **PyPSA-Earth Version:** `0.4.0`

!!! note "Validation Baseline Caveat"
    This validation scenario was solved using renewable capacity lower limits set to historical **2020** levels (`estimate_renewable_capacities: stats: "irena"` referencing 2020).
    Since the target year is 2021, and the model was not forced to build up to 2021 levels (only allowed to expand if economically optimal), this difference in baseline capacity can result in negative deviations when comparing model outputs against actual 2021 reference statistics.

### 1. Electricity Demand

| Source         |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------------|--------------------:|------------------------:|:----------------|:--------|
| ember          |              267.36 |                  267.45 | -0.03%          | A       |
| ourworldindata |              267.36 |                  267.45 | -0.03%          | A       |

### 2. Installed Capacity

**Total Installed Capacity Comparison:**

| Source   |   Model Value (MW) |   Reference Value (MW) | Deviation (%)   | Grade   |
|:---------|-------------------:|-----------------------:|:----------------|:--------|
| ember    |            89240.9 |                95400   | -6.46%          | B       |
| irena    |            89240.9 |                96697.1 | -7.71%          | B       |

### 3. Electricity Generation

**Total Generation Comparison:**

| Source   |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------|--------------------:|------------------------:|:----------------|:--------|
| ember    |              228.89 |                  267.45 | -14.42%         | C       |

---

## Brazil (BR) — Scenario `BR_2021`

* **Model Year:** 2021
* **PyPSA-Earth Version:** `0.4.0`

!!! note "Validation Baseline Caveat"
    This validation scenario was solved using renewable capacity lower limits set to historical **2020** levels (`estimate_renewable_capacities: stats: "irena"` referencing 2020).
    Since the target year is 2021, and the model was not forced to build up to 2021 levels (only allowed to expand if economically optimal), this difference in baseline capacity can result in negative deviations when comparing model outputs against actual 2021 reference statistics.

### 1. Electricity Demand

| Source         |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------------|--------------------:|------------------------:|:----------------|:--------|
| ember          |              685.57 |                  679.5  | +0.89%          | A       |
| ourworldindata |              685.57 |                  679.21 | +0.94%          | A       |

### 2. Installed Capacity

**Total Installed Capacity Comparison:**

| Source   |   Model Value (MW) |   Reference Value (MW) | Deviation (%)   | Grade   |
|:---------|-------------------:|-----------------------:|:----------------|:--------|
| ember    |             193312 |                 192940 | +0.19%          | A       |
| irena    |             193312 |                 193688 | -0.19%          | A       |

### 3. Electricity Generation

**Total Generation Comparison:**

| Source   |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------|--------------------:|------------------------:|:----------------|:--------|
| ember    |               603.9 |                   656.4 | -8.00%          | B       |

---

## China (CN) — Scenario `CN_2021`

* **Model Year:** 2021
* **PyPSA-Earth Version:** `0.4.0`

!!! note "Validation Baseline Caveat"
    This validation scenario was solved using renewable capacity lower limits set to historical **2020** levels (`estimate_renewable_capacities: stats: "irena"` referencing 2020).
    Since the target year is 2021, and the model was not forced to build up to 2021 levels (only allowed to expand if economically optimal), this difference in baseline capacity can result in negative deviations when comparing model outputs against actual 2021 reference statistics.

### 1. Electricity Demand

| Source         |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------------|--------------------:|------------------------:|:----------------|:--------|
| ember          |             8515.64 |                 8520.02 | -0.05%          | A       |
| ourworldindata |             8515.64 |                 8520.02 | -0.05%          | A       |

### 2. Installed Capacity

**Total Installed Capacity Comparison:**

| Source   |   Model Value (MW) |   Reference Value (MW) | Deviation (%)   | Grade   |
|:---------|-------------------:|-----------------------:|:----------------|:--------|
| ember    |        2.51737e+06 |            2.25203e+06 | +11.78%         | C       |
| irena    |        2.51737e+06 |            2.36722e+06 | +6.34%          | B       |

### 3. Electricity Generation

**Total Generation Comparison:**

| Source   |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------|--------------------:|------------------------:|:----------------|:--------|
| ember    |                   0 |                 8534.26 | -100.00%        | D       |

---

## Colombia (CO) — Scenario `CO_2021`

* **Model Year:** 2021
* **PyPSA-Earth Version:** `0.4.0`

!!! note "Validation Baseline Caveat"
    This validation scenario was solved using renewable capacity lower limits set to historical **2020** levels (`estimate_renewable_capacities: stats: "irena"` referencing 2020).
    Since the target year is 2021, and the model was not forced to build up to 2021 levels (only allowed to expand if economically optimal), this difference in baseline capacity can result in negative deviations when comparing model outputs against actual 2021 reference statistics.

### 1. Electricity Demand

| Source         |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------------|--------------------:|------------------------:|:----------------|:--------|
| ember          |               81.37 |                   84.48 | -3.68%          | A       |
| ourworldindata |               81.37 |                   84.54 | -3.75%          | A       |

### 2. Installed Capacity

**Total Installed Capacity Comparison:**

| Source   |   Model Value (MW) |   Reference Value (MW) | Deviation (%)   | Grade   |
|:---------|-------------------:|-----------------------:|:----------------|:--------|
| ember    |            21592.6 |                19080   | +13.17%         | C       |
| irena    |            21592.6 |                18416.4 | +17.25%         | C       |

### 3. Electricity Generation

**Total Generation Comparison:**

| Source   |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------|--------------------:|------------------------:|:----------------|:--------|
| ember    |               81.37 |                   84.36 | -3.54%          | A       |

---

## Germany (DE) — Scenario `DE_2021`

* **Model Year:** 2021
* **PyPSA-Earth Version:** `0.4.0`

!!! note "Validation Baseline Caveat"
    This validation scenario was solved using renewable capacity lower limits set to historical **2020** levels (`estimate_renewable_capacities: stats: "irena"` referencing 2020).
    Since the target year is 2021, and the model was not forced to build up to 2021 levels (only allowed to expand if economically optimal), this difference in baseline capacity can result in negative deviations when comparing model outputs against actual 2021 reference statistics.

### 1. Electricity Demand

| Source         |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------------|--------------------:|------------------------:|:----------------|:--------|
| ember          |              560.73 |                  560.25 | +0.09%          | A       |
| ourworldindata |              560.73 |                  560.73 | +0.00%          | A       |

### 2. Installed Capacity

**Total Installed Capacity Comparison:**

| Source   |   Model Value (MW) |   Reference Value (MW) | Deviation (%)   | Grade   |
|:---------|-------------------:|-----------------------:|:----------------|:--------|
| ember    |             215176 |                 218990 | -1.74%          | A       |
| irena    |             215176 |                 241608 | -10.94%         | C       |

### 3. Electricity Generation

**Total Generation Comparison:**

| Source   |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------|--------------------:|------------------------:|:----------------|:--------|
| ember    |              559.66 |                  578.83 | -3.31%          | A       |

---

## India (IN) — Scenario `IN_2021`

* **Model Year:** 2021
* **PyPSA-Earth Version:** `0.4.0`

!!! note "Validation Baseline Caveat"
    This validation scenario was solved using renewable capacity lower limits set to historical **2020** levels (`estimate_renewable_capacities: stats: "irena"` referencing 2020).
    Since the target year is 2021, and the model was not forced to build up to 2021 levels (only allowed to expand if economically optimal), this difference in baseline capacity can result in negative deviations when comparing model outputs against actual 2021 reference statistics.

### 1. Electricity Demand

| Source         |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------------|--------------------:|------------------------:|:----------------|:--------|
| ember          |             1712.88 |                 1678.69 | +2.04%          | A       |
| ourworldindata |             1712.88 |                 1714.73 | -0.11%          | A       |

### 2. Installed Capacity

**Total Installed Capacity Comparison:**

| Source   |   Model Value (MW) |   Reference Value (MW) | Deviation (%)   | Grade   |
|:---------|-------------------:|-----------------------:|:----------------|:--------|
| ember    |             509813 |                 435090 | +17.17%         | C       |
| irena    |             509813 |                 464572 | +9.74%          | B       |

### 3. Electricity Generation

**Total Generation Comparison:**

| Source   |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------|--------------------:|------------------------:|:----------------|:--------|
| ember    |             1712.88 |                 1678.72 | +2.03%          | A       |

---

## Italy (IT) — Scenario `IT_2021`

* **Model Year:** 2021
* **PyPSA-Earth Version:** `0.4.0`

!!! note "Validation Baseline Caveat"
    This validation scenario was solved using renewable capacity lower limits set to historical **2020** levels (`estimate_renewable_capacities: stats: "irena"` referencing 2020).
    Since the target year is 2021, and the model was not forced to build up to 2021 levels (only allowed to expand if economically optimal), this difference in baseline capacity can result in negative deviations when comparing model outputs against actual 2021 reference statistics.

### 1. Electricity Demand

| Source         |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------------|--------------------:|------------------------:|:----------------|:--------|
| ember          |              328.28 |                  328.28 | +0.00%          | A       |
| ourworldindata |              328.28 |                  328.28 | +0.00%          | A       |

### 2. Installed Capacity

**Total Installed Capacity Comparison:**

| Source   |   Model Value (MW) |   Reference Value (MW) | Deviation (%)   | Grade   |
|:---------|-------------------:|-----------------------:|:----------------|:--------|
| ember    |             113404 |                 121060 | -6.32%          | B       |
| irena    |             113404 |                 116748 | -2.86%          | A       |

### 3. Electricity Generation

**Total Generation Comparison:**

| Source   |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------|--------------------:|------------------------:|:----------------|:--------|
| ember    |              327.95 |                  285.49 | +14.87%         | C       |

---

## Mexico (MX) — Scenario `MX_2021`

* **Model Year:** 2021
* **PyPSA-Earth Version:** `0.4.0`

!!! note "Validation Baseline Caveat"
    This validation scenario was solved using renewable capacity lower limits set to historical **2020** levels (`estimate_renewable_capacities: stats: "irena"` referencing 2020).
    Since the target year is 2021, and the model was not forced to build up to 2021 levels (only allowed to expand if economically optimal), this difference in baseline capacity can result in negative deviations when comparing model outputs against actual 2021 reference statistics.

### 1. Electricity Demand

| Source         |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------------|--------------------:|------------------------:|:----------------|:--------|
| ember          |              339.15 |                  327.63 | +3.52%          | A       |
| ourworldindata |              339.15 |                  329.04 | +3.07%          | A       |

### 2. Installed Capacity

**Total Installed Capacity Comparison:**

| Source   |   Model Value (MW) |   Reference Value (MW) | Deviation (%)   | Grade   |
|:---------|-------------------:|-----------------------:|:----------------|:--------|
| ember    |            97754.6 |                 106600 | -8.30%          | B       |
| irena    |            97754.6 |                 101519 | -3.71%          | A       |

### 3. Electricity Generation

**Total Generation Comparison:**

| Source   |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------|--------------------:|------------------------:|:----------------|:--------|
| ember    |              284.07 |                  328.59 | -13.55%         | C       |

---

## Nigeria (NG) — Scenario `NG_2021`

* **Model Year:** 2021
* **PyPSA-Earth Version:** `0.4.0`

!!! note "Validation Baseline Caveat"
    This validation scenario was solved using renewable capacity lower limits set to historical **2020** levels (`estimate_renewable_capacities: stats: "irena"` referencing 2020).
    Since the target year is 2021, and the model was not forced to build up to 2021 levels (only allowed to expand if economically optimal), this difference in baseline capacity can result in negative deviations when comparing model outputs against actual 2021 reference statistics.

### 1. Electricity Demand

| Source         |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------------|--------------------:|------------------------:|:----------------|:--------|
| ember          |               31.47 |                   36.14 | -12.92%         | C       |
| ourworldindata |               31.47 |                   36.06 | -12.73%         | C       |

### 2. Installed Capacity

**Total Installed Capacity Comparison:**

| Source   |   Model Value (MW) |   Reference Value (MW) | Deviation (%)   | Grade   |
|:---------|-------------------:|-----------------------:|:----------------|:--------|
| ember    |            17212.3 |                13800   | +24.73%         | D       |
| irena    |            17212.3 |                13254.9 | +29.86%         | D       |

### 3. Electricity Generation

**Total Generation Comparison:**

| Source   |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------|--------------------:|------------------------:|:----------------|:--------|
| ember    |               31.47 |                    39.2 | -19.72%         | C       |

---

## United States (US) — Scenario `US_2021`

* **Model Year:** 2021
* **PyPSA-Earth Version:** `0.4.0`

!!! note "Validation Baseline Caveat"
    This validation scenario was solved using renewable capacity lower limits set to historical **2020** levels (`estimate_renewable_capacities: stats: "irena"` referencing 2020).
    Since the target year is 2021, and the model was not forced to build up to 2021 levels (only allowed to expand if economically optimal), this difference in baseline capacity can result in negative deviations when comparing model outputs against actual 2021 reference statistics.

### 1. Electricity Demand

| Source         |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------------|--------------------:|------------------------:|:----------------|:--------|
| ember          |             4191.63 |                 4192.93 | -0.03%          | A       |
| ourworldindata |             4191.63 |                 4192.93 | -0.03%          | A       |

### 2. Installed Capacity

**Total Installed Capacity Comparison:**

| Source   |   Model Value (MW) |   Reference Value (MW) | Deviation (%)   | Grade   |
|:---------|-------------------:|-----------------------:|:----------------|:--------|
| ember    |         1.4283e+06 |            1.20502e+06 | +18.53%         | C       |
| irena    |         1.4283e+06 |            1.17435e+06 | +21.62%         | D       |

### 3. Electricity Generation

**Total Generation Comparison:**

| Source   |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------|--------------------:|------------------------:|:----------------|:--------|
| ember    |             4182.39 |                 4153.62 | +0.69%          | A       |

---

## South Africa (ZA) — Scenario `ZA_2021`

* **Model Year:** 2021
* **PyPSA-Earth Version:** `0.4.0`

!!! note "Validation Baseline Caveat"
    This validation scenario was solved using renewable capacity lower limits set to historical **2020** levels (`estimate_renewable_capacities: stats: "irena"` referencing 2020).
    Since the target year is 2021, and the model was not forced to build up to 2021 levels (only allowed to expand if economically optimal), this difference in baseline capacity can result in negative deviations when comparing model outputs against actual 2021 reference statistics.

### 1. Electricity Demand

| Source         |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------------|--------------------:|------------------------:|:----------------|:--------|
| ember          |              218.84 |                  241.89 | -9.53%          | B       |
| ourworldindata |              218.84 |                  240.74 | -9.10%          | B       |

### 2. Installed Capacity

**Total Installed Capacity Comparison:**

| Source   |   Model Value (MW) |   Reference Value (MW) | Deviation (%)   | Grade   |
|:---------|-------------------:|-----------------------:|:----------------|:--------|
| ember    |            65637.6 |                59620   | +10.09%         | C       |
| irena    |            65637.6 |                61951.7 | +5.95%          | B       |

### 3. Electricity Generation

**Total Generation Comparison:**

| Source   |   Model Value (TWh) |   Reference Value (TWh) | Deviation (%)   | Grade   |
|:---------|--------------------:|------------------------:|:----------------|:--------|
| ember    |              218.84 |                  245.46 | -10.84%         | C       |

---
