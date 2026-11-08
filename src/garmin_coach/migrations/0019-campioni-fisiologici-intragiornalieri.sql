-- Campioni reali della Personal API. Nessuna interpolazione dei giorni mancanti.
CREATE TABLE IF NOT EXISTS health_samples (
    sample_date DATE NOT NULL,
    metric VARCHAR NOT NULL,
    observed_at TIMESTAMP NOT NULL,
    value DOUBLE,
    source_object_id VARCHAR NOT NULL,
    imported_at TIMESTAMP NOT NULL,
    PRIMARY KEY(sample_date, metric, observed_at)
);
CREATE TABLE IF NOT EXISTS health_sample_imports (
    sample_date DATE NOT NULL,
    metric VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    status VARCHAR NOT NULL,
    source_object_id VARCHAR NOT NULL,
    PRIMARY KEY(sample_date, metric)
);
