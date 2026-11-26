ALTER TABLE entries ADD COLUMN account TEXT NOT NULL DEFAULT 'bank' CHECK(account IN ('bank','cash'));
ALTER TABLE entries ADD COLUMN for_period TEXT;
UPDATE entries SET account='cash' WHERE method='מזומן';
CREATE INDEX entries_account ON entries(account,day,id);
CREATE INDEX entries_for_period ON entries(unit,for_period);

CREATE TABLE cash_transfers (
 id INTEGER PRIMARY KEY,
 day TEXT NOT NULL,
 recorded TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 from_account TEXT NOT NULL CHECK(from_account IN ('bank','cash')),
 to_account TEXT NOT NULL CHECK(to_account IN ('bank','cash')),
 amount INTEGER NOT NULL CHECK(amount > 0),
 reference TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 CHECK(from_account <> to_account)
);
CREATE INDEX cash_transfers_day ON cash_transfers(day,id);

CREATE TABLE excel_history (
 unit INTEGER NOT NULL REFERENCES units(id),
 year INTEGER NOT NULL,
 month INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
 paid INTEGER NOT NULL CHECK(paid IN (0,1)),
 PRIMARY KEY(unit,year,month)
);

CREATE TABLE compensation_checks (
 unit INTEGER NOT NULL REFERENCES units(id),
 year INTEGER NOT NULL,
 amount_text TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(unit,year)
);
