-- Enforce immutability below the application adapter after first byte upload.
CREATE FUNCTION enforce_source_artifact_immutability() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.id IS DISTINCT FROM OLD.id
 OR NEW.kind IS DISTINCT FROM OLD.kind OR NEW.filename IS DISTINCT FROM OLD.filename
 OR NEW.sha256 IS DISTINCT FROM OLD.sha256 OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
 OR NEW.declared_media_type IS DISTINCT FROM OLD.declared_media_type OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
  RAISE EXCEPTION 'Source artifact intent metadata is immutable';
 END IF;
 IF OLD.content_base64 IS NOT NULL AND
 (NEW.content_base64 IS DISTINCT FROM OLD.content_base64 OR NEW.object_generation IS DISTINCT FROM OLD.object_generation) THEN
  RAISE EXCEPTION 'Uploaded source artifact bytes and generation are immutable';
 END IF;
 IF NEW.status IS DISTINCT FROM OLD.status AND NOT
 ((OLD.status='INTENT_ISSUED' AND NEW.status IN ('QUARANTINED','REJECTED'))
 OR (OLD.status='QUARANTINED' AND NEW.status IN ('AVAILABLE','REJECTED'))) THEN
  RAISE EXCEPTION 'Source artifact state transition is not permitted';
 END IF;
 IF NEW.status IN ('QUARANTINED','AVAILABLE') AND (NEW.content_base64 IS NULL OR NEW.object_generation IS NULL) THEN
  RAISE EXCEPTION 'Source artifact availability requires uploaded bytes and generation';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER source_artifact_immutable BEFORE UPDATE ON source_artifacts FOR EACH ROW EXECUTE FUNCTION enforce_source_artifact_immutability();
