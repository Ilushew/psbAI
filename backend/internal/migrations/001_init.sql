-- +goose Up
CREATE TABLE IF NOT EXISTS schema_check (
    id BIGSERIAL PRIMARY KEY
);

-- +goose Down
DROP TABLE IF EXISTS schema_check;