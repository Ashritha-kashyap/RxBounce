-- =====================================================================
-- RxBounce : Pharmacy Bounce Rate Reduction  |  MySQL 8 schema
-- ER diagram: MySQL Workbench > Database > Reverse Engineer > pharmacy_bounce
-- =====================================================================

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS alerts, reorder_policy, forecasts, model_metrics, feature_importance,
    simulation_results, simulation_breakdown, model_ablation, sensitivity_results, drug_substitutes, inventory_batches, stock_on_hand,
    daily_stock, po_items, purchase_orders, prescription_items, returns, sales_transactions,
    prescriptions, calendar, holidays, drug_supplier, suppliers, drugs, patients, doctors,
    specialisations, departments, users;
SET FOREIGN_KEY_CHECKS = 1;

-- ---------------- master data ----------------
CREATE TABLE departments (
    dept_id      VARCHAR(10) PRIMARY KEY,
    dept_name    VARCHAR(50) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE specialisations (
    spec_id      VARCHAR(10) PRIMARY KEY,
    spec_name    VARCHAR(100) NOT NULL,
    dept_id      VARCHAR(10) NOT NULL,
    FOREIGN KEY (dept_id) REFERENCES departments(dept_id)
) ENGINE=InnoDB;

CREATE TABLE doctors (
    doctor_id    VARCHAR(10) PRIMARY KEY,
    doctor_name  VARCHAR(100) NOT NULL,
    spec_id      VARCHAR(10) NOT NULL,
    FOREIGN KEY (spec_id) REFERENCES specialisations(spec_id)
) ENGINE=InnoDB;

CREATE TABLE patients (
    patient_id        BIGINT PRIMARY KEY,
    first_visit_date  DATE,
    visit_count       INT
) ENGINE=InnoDB;

CREATE TABLE drugs (
    drug_id           VARCHAR(10) PRIMARY KEY,
    drug_name         VARCHAR(255) NOT NULL,
    salt_composition  VARCHAR(255),
    strength          VARCHAR(120),
    formulation       VARCHAR(50),
    subcat            VARCHAR(100),
    subcat1           VARCHAR(100),
    abc_class         CHAR(1),
    unit_cost         DECIMAL(12,2),
    unit_mrp          DECIMAL(12,2),
    pack_size         INT DEFAULT 1,
    is_formulary      TINYINT(1) DEFAULT 1,
    is_cold_chain     TINYINT(1) DEFAULT 0,
    INDEX idx_drug_name (drug_name),
    INDEX idx_salt (salt_composition)
) ENGINE=InnoDB;

CREATE TABLE suppliers (
    supplier_id          VARCHAR(10) PRIMARY KEY,
    supplier_name        VARCHAR(120) NOT NULL,
    category_served      VARCHAR(120),
    supplier_type        VARCHAR(30),
    base_lead_time_days  INT,
    on_time_rate         DECIMAL(4,2)
) ENGINE=InnoDB;

CREATE TABLE drug_supplier (
    drug_id         VARCHAR(10) PRIMARY KEY,
    supplier_id     VARCHAR(10) NOT NULL,
    lead_time_mean  INT,
    lead_time_sd    DECIMAL(5,1),
    min_order_qty   INT,
    FOREIGN KEY (drug_id) REFERENCES drugs(drug_id),
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
) ENGINE=InnoDB;

CREATE TABLE holidays (
    holiday_date  DATE PRIMARY KEY,
    holiday_name  VARCHAR(100),
    holiday_type  VARCHAR(20)
) ENGINE=InnoDB;

CREATE TABLE calendar (
    cal_date      DATE PRIMARY KEY,
    day_name      VARCHAR(10),
    week_no       INT,
    month_no      INT,
    month_name    CHAR(3),
    quarter       INT,
    year_no       INT,
    is_weekend    TINYINT(1),
    is_holiday    TINYINT(1),
    holiday_name  VARCHAR(100)
) ENGINE=InnoDB;

-- ---------------- transactions ----------------
CREATE TABLE prescriptions (
    rx_id       VARCHAR(20) PRIMARY KEY,
    patient_id  BIGINT NOT NULL,
    doctor_id   VARCHAR(10),
    spec_id     VARCHAR(10),
    rx_date     DATE NOT NULL,
    source      VARCHAR(30),
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (doctor_id) REFERENCES doctors(doctor_id),
    FOREIGN KEY (spec_id) REFERENCES specialisations(spec_id),
    INDEX idx_rx_date (rx_date)
) ENGINE=InnoDB;

CREATE TABLE sales_transactions (
    txn_id       VARCHAR(20) PRIMARY KEY,
    rx_id        VARCHAR(20),
    patient_id   BIGINT,
    drug_id      VARCHAR(10),
    spec_id      VARCHAR(10),
    dept_id      VARCHAR(10),
    txn_date     DATE,
    quantity     INT,
    final_cost   DECIMAL(12,3),
    final_sales  DECIMAL(12,3),
    FOREIGN KEY (rx_id) REFERENCES prescriptions(rx_id),
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (drug_id) REFERENCES drugs(drug_id),
    FOREIGN KEY (spec_id) REFERENCES specialisations(spec_id),
    FOREIGN KEY (dept_id) REFERENCES departments(dept_id),
    INDEX idx_txn_date (txn_date)
) ENGINE=InnoDB;

CREATE TABLE returns (
    return_id    VARCHAR(20) PRIMARY KEY,
    patient_id   BIGINT,
    drug_id      VARCHAR(10),
    spec_id      VARCHAR(10),
    dept_id      VARCHAR(10),
    return_date  DATE,
    return_qty   INT,
    rtn_mrp      DECIMAL(12,3),
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (drug_id) REFERENCES drugs(drug_id),
    FOREIGN KEY (spec_id) REFERENCES specialisations(spec_id),
    FOREIGN KEY (dept_id) REFERENCES departments(dept_id)
) ENGINE=InnoDB;

CREATE TABLE prescription_items (
    rx_item_id          VARCHAR(20) PRIMARY KEY,
    rx_id               VARCHAR(20) NOT NULL,
    drug_id             VARCHAR(10) NOT NULL,
    qty_requested       INT NOT NULL,
    qty_dispensed       INT NOT NULL,
    status              VARCHAR(25) NOT NULL,      -- Fulfilled / Partial / Bounced / Fulfilled (substitute)
    bounce_reason       VARCHAR(40),               -- Out of stock / Insufficient quantity / Not stocked
    txn_id              VARCHAR(20),
    substitute_drug_id  VARCHAR(10),
    FOREIGN KEY (rx_id) REFERENCES prescriptions(rx_id),
    FOREIGN KEY (drug_id) REFERENCES drugs(drug_id),
    FOREIGN KEY (txn_id) REFERENCES sales_transactions(txn_id),
    FOREIGN KEY (substitute_drug_id) REFERENCES drugs(drug_id),
    INDEX idx_status (status)
) ENGINE=InnoDB;

-- ---------------- inventory ----------------
CREATE TABLE purchase_orders (
    po_id          VARCHAR(20) PRIMARY KEY,
    supplier_id    VARCHAR(10) NOT NULL,
    order_date     DATE,
    expected_date  DATE,
    received_date  DATE,
    po_type        VARCHAR(20),                    -- Regular / Emergency / Manual
    status         VARCHAR(20),                    -- Open / Received
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
) ENGINE=InnoDB;

CREATE TABLE po_items (
    po_item_id  VARCHAR(20) PRIMARY KEY,
    po_id       VARCHAR(20) NOT NULL,
    drug_id     VARCHAR(10) NOT NULL,
    order_qty   INT,
    unit_cost   DECIMAL(12,2),
    FOREIGN KEY (po_id) REFERENCES purchase_orders(po_id),
    FOREIGN KEY (drug_id) REFERENCES drugs(drug_id)
) ENGINE=InnoDB;

CREATE TABLE daily_stock (
    drug_id        VARCHAR(10) NOT NULL,
    stock_date     DATE NOT NULL,
    opening_qty    INT,
    received_qty   INT,
    emergency_qty  INT,
    returned_qty   INT,
    dispensed_qty  INT,
    unmet_qty      INT,
    closing_qty    INT,
    on_order_qty   INT,
    PRIMARY KEY (drug_id, stock_date),
    FOREIGN KEY (drug_id) REFERENCES drugs(drug_id)
) ENGINE=InnoDB;

CREATE TABLE stock_on_hand (
    drug_id       VARCHAR(10) PRIMARY KEY,
    qty_on_hand   INT NOT NULL,
    on_order_qty  INT DEFAULT 0,
    updated_at    DATETIME,
    FOREIGN KEY (drug_id) REFERENCES drugs(drug_id)
) ENGINE=InnoDB;

CREATE TABLE inventory_batches (
    batch_id       VARCHAR(20) PRIMARY KEY,
    drug_id        VARCHAR(10) NOT NULL,
    lot_no         VARCHAR(20),
    received_date  DATE,
    mfg_date       DATE,
    expiry_date    DATE,
    qty_remaining  INT,
    unit_cost      DECIMAL(12,2),
    FOREIGN KEY (drug_id) REFERENCES drugs(drug_id),
    INDEX idx_expiry (expiry_date)
) ENGINE=InnoDB;

CREATE TABLE drug_substitutes (
    drug_id             VARCHAR(10) NOT NULL,
    substitute_drug_id  VARCHAR(10) NOT NULL,
    match_type          VARCHAR(40),
    similarity          DECIMAL(5,3),
    rank_no             INT,
    PRIMARY KEY (drug_id, substitute_drug_id),
    FOREIGN KEY (drug_id) REFERENCES drugs(drug_id),
    FOREIGN KEY (substitute_drug_id) REFERENCES drugs(drug_id)
) ENGINE=InnoDB;

-- ---------------- ML outputs ----------------
CREATE TABLE forecasts (
    forecast_id    INT AUTO_INCREMENT PRIMARY KEY,
    drug_id        VARCHAR(10) NOT NULL,
    week_start     DATE NOT NULL,
    actual_qty     DECIMAL(10,2),
    predicted_qty  DECIMAL(10,2),
    sigma_weekly   DECIMAL(10,3),
    is_future      TINYINT(1),
    model_version  VARCHAR(40),
    FOREIGN KEY (drug_id) REFERENCES drugs(drug_id),
    INDEX idx_fc (drug_id, week_start)
) ENGINE=InnoDB;

CREATE TABLE reorder_policy (
    drug_id              VARCHAR(10) PRIMARY KEY,
    avg_daily_forecast   DECIMAL(10,3),
    safety_stock         DECIMAL(10,2),
    reorder_point        INT,
    order_up_to          INT,
    suggested_order_qty  INT,
    stockout_risk        DECIMAL(6,4),
    risk_band            VARCHAR(10),
    updated_at           DATETIME,
    FOREIGN KEY (drug_id) REFERENCES drugs(drug_id)
) ENGINE=InnoDB;

CREATE TABLE alerts (
    alert_id     INT AUTO_INCREMENT PRIMARY KEY,
    drug_id      VARCHAR(10) NOT NULL,
    alert_type   VARCHAR(30),
    severity     VARCHAR(10),
    message      VARCHAR(300),
    created_at   DATETIME,
    is_resolved  TINYINT(1) DEFAULT 0,
    FOREIGN KEY (drug_id) REFERENCES drugs(drug_id)
) ENGINE=InnoDB;

CREATE TABLE model_metrics (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    task         VARCHAR(50),
    model        VARCHAR(50),
    is_selected  TINYINT(1),
    metric       VARCHAR(30),
    value        DOUBLE
) ENGINE=InnoDB;

CREATE TABLE feature_importance (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    feature     VARCHAR(50),
    importance  DOUBLE,
    method      VARCHAR(40),
    model       VARCHAR(40)
) ENGINE=InnoDB;

CREATE TABLE simulation_results (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    scenario  VARCHAR(50),
    metric    VARCHAR(50),
    value     DOUBLE
) ENGINE=InnoDB;

CREATE TABLE simulation_breakdown (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    scenario      VARCHAR(50),
    month         VARCHAR(10),
    bounce_rate   DOUBLE,
    lost_revenue  DOUBLE
) ENGINE=InnoDB;

CREATE TABLE model_ablation (
    id                            INT AUTO_INCREMENT PRIMARY KEY,
    step                          VARCHAR(60),
    bounce_rate                   DOUBLE,
    bounce_reduction_pct          DOUBLE,
    revenue_recovered_annual_inr  DOUBLE,
    avg_inventory_value_inr       DOUBLE
) ENGINE=InnoDB;

CREATE TABLE sensitivity_results (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    case_name             VARCHAR(60),
    old_bounce_rate       DOUBLE,
    rxbounce_bounce_rate  DOUBLE,
    bounce_reduction_pct  DOUBLE,
    meets_target          TINYINT(1)
) ENGINE=InnoDB;

-- ---------------- application ----------------
CREATE TABLE users (
    user_id        INT AUTO_INCREMENT PRIMARY KEY,
    username       VARCHAR(50) UNIQUE NOT NULL,
    password_hash  CHAR(64) NOT NULL,
    full_name      VARCHAR(100),
    role           VARCHAR(20) NOT NULL          -- manager / pharmacist
) ENGINE=InnoDB;
