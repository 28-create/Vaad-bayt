CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE buildings (id INTEGER PRIMARY KEY, apartments INTEGER NOT NULL);
CREATE TABLE units (
 id INTEGER PRIMARY KEY, building INTEGER NOT NULL REFERENCES buildings(id), slot INTEGER NOT NULL,
 apartment TEXT NOT NULL DEFAULT '', subunit TEXT NOT NULL DEFAULT '',
 owner TEXT NOT NULL DEFAULT '', tenant TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
 email TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
 UNIQUE(building,slot), UNIQUE(building,apartment,subunit)
);
CREATE TABLE unit_status (
 unit INTEGER NOT NULL REFERENCES units(id), effective TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)),
 PRIMARY KEY(unit,effective)
);
CREATE TABLE fee_rates (
 unit INTEGER NOT NULL REFERENCES units(id), effective TEXT NOT NULL,
 amount INTEGER NOT NULL CHECK(amount>=0), PRIMARY KEY(unit,effective)
);
CREATE TABLE categories (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('expense','income')),
 name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, UNIQUE(kind,name)
);
CREATE TABLE entries (
 id INTEGER PRIMARY KEY, unit INTEGER REFERENCES units(id), day TEXT NOT NULL,
 recorded TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 kind TEXT NOT NULL CHECK(kind IN ('opening','charge','adjustment','payment','expense','income','reversal')),
 debit INTEGER NOT NULL DEFAULT 0, cash INTEGER NOT NULL DEFAULT 0,
 period TEXT, original INTEGER UNIQUE REFERENCES entries(id),
 charge INTEGER REFERENCES entries(id), category INTEGER REFERENCES categories(id),
 method TEXT NOT NULL DEFAULT '', party TEXT NOT NULL DEFAULT '', reference TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', token TEXT UNIQUE,
 CHECK((kind IN ('opening','charge','adjustment','payment'))=(unit IS NOT NULL) OR kind='reversal'),
 CHECK((kind='charge')=(period IS NOT NULL)),
 CHECK((kind='adjustment')=(charge IS NOT NULL)),
 CHECK((kind='reversal')=(original IS NOT NULL)),
 CHECK(kind!='payment' OR (cash>0 AND debit=-cash)),
 CHECK(kind!='expense' OR (cash<0 AND debit=0)),
 CHECK(kind!='income' OR (cash>0 AND debit=0)),
 CHECK(kind NOT IN ('opening','charge','adjustment') OR cash=0)
);
CREATE UNIQUE INDEX monthly_once ON entries(unit,period) WHERE kind='charge';
CREATE UNIQUE INDEX opening_once ON entries(unit) WHERE kind='opening';
CREATE INDEX unit_history ON entries(unit,day,id);
CREATE INDEX cash_history ON entries(day,id) WHERE cash<>0;
