-- Online Store: draft schema (PostgreSQL).
-- For MySQL: BIGSERIAL -> BIGINT AUTO_INCREMENT, JSONB -> JSON, TIMESTAMPTZ -> TIMESTAMP.

CREATE TABLE users (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(20)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(10)  NOT NULL DEFAULT 'customer' CHECK (role IN ('customer', 'admin')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- One row per user. Columns are nullable because sign-up collects only name/email/phone;
-- the app treats the profile as "complete" once the required delivery fields are filled.
CREATE TABLE profiles (
    user_id        BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    full_name      VARCHAR(100),
    email          VARCHAR(255),
    phone          VARCHAR(20),
    alt_phone      VARCHAR(20),
    address_line1  VARCHAR(200),
    address_line2  VARCHAR(200),
    city           VARCHAR(100),
    state          VARCHAR(100),
    postal_code    VARCHAR(10),
    country        VARCHAR(60),
    address_type   VARCHAR(10) NOT NULL DEFAULT 'Home' CHECK (address_type IN ('Home', 'Work')),
    delivery_notes VARCHAR(300),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE products (
    id          BIGSERIAL PRIMARY KEY,
    sku         VARCHAR(40)   NOT NULL UNIQUE,   -- stable key used by the bulk importer (upsert)
    name        VARCHAR(150)  NOT NULL,
    category    VARCHAR(60)   NOT NULL,
    brand       VARCHAR(80),
    price       NUMERIC(10,2) NOT NULL CHECK (price >= 0),
    stock       INTEGER       NOT NULL DEFAULT 0 CHECK (stock >= 0),
    description TEXT          NOT NULL DEFAULT '',
    image_path  VARCHAR(255),                    -- relative to frontend/assets/images, e.g. electronics/wireless-mouse.png
    is_active   BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX idx_products_category ON products (category);

CREATE TABLE carts (
    id      BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE cart_items (
    cart_id    BIGINT  NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    product_id BIGINT  NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity   INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (cart_id, product_id)
);

CREATE TABLE coupons (
    code             VARCHAR(30) PRIMARY KEY,
    discount_percent INTEGER     NOT NULL CHECK (discount_percent BETWEEN 1 AND 100),
    active           BOOLEAN     NOT NULL DEFAULT TRUE,
    expires_at       TIMESTAMPTZ
);

CREATE TABLE orders (
    id             BIGSERIAL PRIMARY KEY,
    user_id        BIGINT        NOT NULL REFERENCES users(id),
    status         VARCHAR(12)   NOT NULL DEFAULT 'Pending'
                   CHECK (status IN ('Pending', 'Paid', 'Shipped', 'Delivered', 'Cancelled')),
    payment_status VARCHAR(20)   NOT NULL DEFAULT 'unpaid'
                   CHECK (payment_status IN ('unpaid', 'due_on_delivery', 'paid', 'failed', 'refunded')),
    subtotal       NUMERIC(10,2) NOT NULL,
    discount       NUMERIC(10,2) NOT NULL DEFAULT 0,
    total          NUMERIC(10,2) NOT NULL,
    coupon_code    VARCHAR(30) REFERENCES coupons(code),
    ship_to        JSONB         NOT NULL,          -- snapshot of the address at order time
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX idx_orders_user ON orders (user_id);

CREATE TABLE order_items (
    id           BIGSERIAL PRIMARY KEY,
    order_id     BIGINT        NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id   BIGINT        REFERENCES products(id) ON DELETE SET NULL,
    product_name VARCHAR(150)  NOT NULL,            -- snapshot
    unit_price   NUMERIC(10,2) NOT NULL,            -- snapshot
    quantity     INTEGER       NOT NULL CHECK (quantity > 0)
);

CREATE TABLE payments (
    id                 BIGSERIAL PRIMARY KEY,
    order_id           BIGINT        NOT NULL REFERENCES orders(id),
    gateway            VARCHAR(20)   NOT NULL,       -- mock | razorpay | stripe
    gateway_payment_id VARCHAR(100)  UNIQUE,
    idempotency_key    VARCHAR(100)  UNIQUE,         -- stops duplicate charges
    method             VARCHAR(30)   NOT NULL,       -- Cash on Delivery | UPI | Card | Net Banking
    amount             NUMERIC(10,2) NOT NULL,
    currency           CHAR(3)       NOT NULL DEFAULT 'INR',
    status             VARCHAR(20)   NOT NULL DEFAULT 'created'
                       CHECK (status IN ('created', 'pending', 'succeeded', 'failed', 'refunded')),
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX idx_payments_order ON payments (order_id);

CREATE TABLE refunds (
    id                BIGSERIAL PRIMARY KEY,
    payment_id        BIGINT        NOT NULL REFERENCES payments(id),
    amount            NUMERIC(10,2) NOT NULL CHECK (amount > 0),
    reason            VARCHAR(200),
    status            VARCHAR(20)   NOT NULL DEFAULT 'requested',
    gateway_refund_id VARCHAR(100),
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- Every webhook / gateway callback, kept for auditing and fraud checks.
CREATE TABLE payment_events (
    id              BIGSERIAL PRIMARY KEY,
    payment_id      BIGINT REFERENCES payments(id),
    event_type      VARCHAR(60) NOT NULL,
    payload         JSONB       NOT NULL,
    signature_valid BOOLEAN     NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reviews (
    id                BIGSERIAL PRIMARY KEY,
    product_id        BIGINT   NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    user_id           BIGINT   NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating            SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    title             VARCHAR(150),
    body              TEXT,
    verified_purchase BOOLEAN  NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_id, user_id)
);

-- Activity used for search history and personal recommendations.
CREATE TABLE search_history (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query       VARCHAR(200) NOT NULL,
    searched_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_search_user ON search_history (user_id, searched_at DESC);

CREATE TABLE product_views (
    user_id    BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id BIGINT      NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    viewed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, product_id)
);
