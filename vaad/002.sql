CREATE TABLE occupants (
 id INTEGER PRIMARY KEY,
 unit INTEGER NOT NULL REFERENCES units(id),
 role TEXT NOT NULL CHECK(role IN ('owner','tenant')),
 name TEXT NOT NULL,
 phone TEXT NOT NULL DEFAULT '',
 email TEXT NOT NULL DEFAULT '',
 arrived TEXT NOT NULL,
 departed TEXT,
 notes TEXT NOT NULL DEFAULT '',
 CHECK(departed IS NULL OR departed >= arrived)
);
CREATE INDEX occupants_unit ON occupants(unit,arrived);
CREATE TABLE suppliers (
 id INTEGER PRIMARY KEY,
 name TEXT NOT NULL UNIQUE,
 service TEXT NOT NULL DEFAULT '',
 phone TEXT NOT NULL DEFAULT '',
 contact TEXT NOT NULL DEFAULT '',
 email TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
ALTER TABLE entries ADD COLUMN supplier INTEGER REFERENCES suppliers(id);
CREATE INDEX entries_supplier ON entries(supplier,day);
CREATE TABLE recurring_expenses (
 id INTEGER PRIMARY KEY,
 supplier INTEGER REFERENCES suppliers(id),
 category INTEGER NOT NULL REFERENCES categories(id),
 usual_amount INTEGER NOT NULL CHECK(usual_amount > 0),
 variable INTEGER NOT NULL DEFAULT 0 CHECK(variable IN (0,1)),
 frequency_months INTEGER NOT NULL CHECK(frequency_months > 0),
 due_day INTEGER NOT NULL CHECK(due_day BETWEEN 1 AND 31),
 starts TEXT NOT NULL,
 ends TEXT,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE recurring_matches (
 recurring INTEGER NOT NULL REFERENCES recurring_expenses(id),
 period TEXT NOT NULL,
 expense INTEGER NOT NULL UNIQUE REFERENCES entries(id),
 PRIMARY KEY(recurring,period)
);

