DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS subjects;
DROP TABLE IF EXISTS level1;
DROP TABLE IF EXISTS level2;
DROP TABLE IF EXISTS resources;
DROP TABLE IF EXISTS activity_log;
DROP TABLE IF EXISTS badges;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(user_id, name)
);

CREATE TABLE subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    level1_label TEXT NOT NULL DEFAULT 'Milestone',
    level2_label TEXT NOT NULL DEFAULT 'Module',
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
);

CREATE TABLE level1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

CREATE TABLE level2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level1_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    notes TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    completed_at TEXT,
    flagged INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (level1_id) REFERENCES level1(id) ON DELETE CASCADE
);

CREATE TABLE resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL,
    level2_id INTEGER,
    type TEXT NOT NULL,
    value TEXT NOT NULL,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY (level2_id) REFERENCES level2(id) ON DELETE CASCADE
);

CREATE TABLE activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    level2_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    FOREIGN KEY (level2_id) REFERENCES level2(id) ON DELETE CASCADE
);

CREATE TABLE badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    level1_id INTEGER NOT NULL,
    earned_date TEXT NOT NULL,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    FOREIGN KEY (level1_id) REFERENCES level1(id) ON DELETE CASCADE
);
