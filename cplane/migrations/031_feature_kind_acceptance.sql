ALTER TABLE cplane_features
    ADD COLUMN kind text CHECK (kind IN ('experience', 'functional'));
ALTER TABLE cplane_features DROP CONSTRAINT cplane_features_stage_check;
ALTER TABLE cplane_features ADD CONSTRAINT cplane_features_stage_check
    CHECK (stage IN ('shortlist', 'grilling', 'ready', 'next', 'building', 'acceptance', 'testing', 'done', 'parked'));
ALTER TABLE cplane_features DROP CONSTRAINT cplane_features_parked_from_check;
ALTER TABLE cplane_features ADD CONSTRAINT cplane_features_parked_from_check
    CHECK (parked_from IN ('shortlist', 'grilling', 'ready', 'next', 'building', 'acceptance', 'testing', 'done'));
