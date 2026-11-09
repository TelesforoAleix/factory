ALTER TABLE cplane_sessions DROP CONSTRAINT cplane_sessions_kind_check;
ALTER TABLE cplane_sessions ADD CHECK (kind IN ('legacy','orchestrator','project','feature','secretary'));
ALTER TABLE cplane_sessions DROP CONSTRAINT cplane_chat_links;
ALTER TABLE cplane_sessions ADD CONSTRAINT cplane_chat_links CHECK (
 (kind = 'legacy' AND project IS NULL AND feature IS NULL) OR
 (kind = 'orchestrator' AND area = 'homelab' AND project IS NULL AND feature IS NULL) OR
 (kind = 'secretary' AND area = 'factory' AND project IS NULL AND feature IS NULL) OR
 (kind = 'project' AND area = 'factory' AND project IS NOT NULL AND feature IS NULL) OR
 (kind = 'feature' AND area = 'factory' AND project IS NOT NULL AND feature IS NOT NULL));
ALTER TABLE cplane_chat_settings DROP CONSTRAINT cplane_chat_settings_kind_check;
ALTER TABLE cplane_chat_settings ADD CHECK (kind IN ('legacy','orchestrator','project','feature','secretary'));
INSERT INTO cplane_chat_settings VALUES ('secretary','codex','gpt-6-luna');
INSERT INTO cplane_sessions (area,title,tool,model,kind) VALUES ('factory','Secretary','codex','gpt-6-luna','secretary');
CREATE UNIQUE INDEX cplane_one_secretary ON cplane_sessions(kind) WHERE kind = 'secretary';
CREATE TABLE cplane_inbox (
 id bigserial PRIMARY KEY, source text NOT NULL CHECK (source IN ('phone','typed')),
 text text NOT NULL CHECK (length(text) <= 16000), fields jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), label jsonb,
 route text NOT NULL DEFAULT 'New' CHECK (route IN ('New','Idea','Delivered → chat','Rejected')),
 wake bigint REFERENCES cplane_session_messages(id), delivery bigint REFERENCES cplane_session_messages(id),
 replied boolean NOT NULL DEFAULT false, transcript text);
CREATE TABLE cplane_inbox_files (
 id bigserial PRIMARY KEY, entry bigint NOT NULL REFERENCES cplane_inbox(id),
 name text NOT NULL, media_type text NOT NULL, content bytea NOT NULL CHECK (octet_length(content) <= 8388608));
CREATE TABLE cplane_ideas (
 id bigserial PRIMARY KEY, title text NOT NULL, note text NOT NULL DEFAULT '', tags jsonb NOT NULL DEFAULT '[]',
 source_entry bigint UNIQUE REFERENCES cplane_inbox(id),
 state text NOT NULL DEFAULT 'new' CHECK (state IN ('new','classified','exploring','promoted','implemented','rejected')),
 exploration_note text NOT NULL DEFAULT '', rejection_reason text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE cplane_idea_features (
 idea bigint REFERENCES cplane_ideas(id), feature bigint REFERENCES cplane_features(feature), PRIMARY KEY (idea,feature));
CREATE TABLE cplane_idea_history (
 id bigserial PRIMARY KEY, idea bigint NOT NULL REFERENCES cplane_ideas(id), actor text NOT NULL,
 event text NOT NULL, state text NOT NULL, time timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE cplane_idea_requests (
 message bigint NOT NULL REFERENCES cplane_session_messages(id), idea bigint NOT NULL REFERENCES cplane_ideas(id),
 action text NOT NULL CHECK (action IN ('explore','promote')), project text REFERENCES cplane_projects(key),
 actor text NOT NULL, completed boolean NOT NULL DEFAULT false, PRIMARY KEY (message,idea));
CREATE TABLE cplane_secretary_questions (
 message bigint PRIMARY KEY REFERENCES cplane_session_messages(id),
 answered boolean NOT NULL DEFAULT false);
CREATE INDEX cplane_inbox_wake ON cplane_inbox(wake);
CREATE INDEX cplane_inbox_pending_reply ON cplane_inbox(delivery) WHERE NOT replied;
CREATE INDEX cplane_inbox_file_entry ON cplane_inbox_files(entry);
CREATE INDEX cplane_idea_feature_done ON cplane_idea_features(feature);
CREATE INDEX cplane_idea_history_order ON cplane_idea_history(idea,id);
