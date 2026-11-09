CREATE INDEX cplane_home_stuck_notices ON cplane_notices ((document->>'id')) WHERE document->>'event' = 'stuck';
CREATE INDEX cplane_home_chat_notices ON cplane_notices ((document->>'chat')) WHERE document->>'event' IN ('owner-check', 'chat-paused');
