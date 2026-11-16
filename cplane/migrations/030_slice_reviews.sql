-- Expand only: old role and outcome writers keep their columns and constraints.
ALTER TABLE cplane_roles DROP CONSTRAINT cplane_roles_role_check;
ALTER TABLE cplane_roles ADD CHECK (role IN (
    'orchestrator','project','feature','secretary','light','standard','strong',
    'reviewer','reviewer-strong'));
INSERT INTO cplane_roles VALUES
    ('reviewer','claude','sonnet','medium'),
    ('reviewer-strong','claude','opus','medium');
ALTER TABLE cplane_slice_outcomes
    ADD COLUMN review_verdict text CHECK (review_verdict IN ('pass','fix','missing')),
    ADD COLUMN review_findings jsonb;
