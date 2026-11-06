CREATE TABLE cplane_slices (
    id text PRIMARY KEY,
    position bigint NOT NULL UNIQUE,
    document jsonb NOT NULL
);
CREATE TABLE cplane_notices (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document jsonb NOT NULL
);
