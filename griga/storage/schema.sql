-- Griga AGI v0.1 — начальная схема (ADR-001, ADR-014).
-- Выполняется идемпотентно: PostgresStorage.init_schema().

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS nodes (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    owner_id UUID REFERENCES users(id) ON DELETE CASCADE,
    confidence REAL NOT NULL DEFAULT 0.5
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes (lower(name));
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes (type);
CREATE INDEX IF NOT EXISTS idx_nodes_owner ON nodes (owner_id);

-- Один глобальный узел на (имя, тип); регистр не важен.
CREATE UNIQUE INDEX IF NOT EXISTS ux_nodes_global_name_type
    ON nodes (lower(name), type)
    WHERE owner_id IS NULL;

-- Один личный узел на (владелец, имя, тип).
CREATE UNIQUE INDEX IF NOT EXISTS ux_nodes_user_name_type
    ON nodes (owner_id, lower(name), type)
    WHERE owner_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS edges (
    id UUID PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target_id UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0.5
        CHECK (weight >= 0.05 AND weight <= 1.0),
    owner_id UUID REFERENCES users(id) ON DELETE CASCADE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ux_edges_triple UNIQUE (source_id, target_id, relation_type),
    CONSTRAINT chk_edges_no_self_loop CHECK (source_id <> target_id)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges (source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges (target_id);
CREATE INDEX IF NOT EXISTS idx_edges_owner ON edges (owner_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges (relation_type);
