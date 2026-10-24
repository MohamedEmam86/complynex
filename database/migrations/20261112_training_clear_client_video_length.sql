-- Training: video lengths are no longer taken from the browser. Clear lengths
-- that a player heartbeat stored (a forged short length let a video count as
-- watched in seconds). They cannot be told apart from an administrator's entry,
-- so only implausible ones are cleared: under 60 seconds while the course's
-- declared duration is at least four times longer. A cleared course falls back
-- to the length read from its uploaded file (on the next heartbeat) or to its
-- declared duration. Idempotent.
BEGIN;
CREATE TEMP TABLE _tc_forged ON COMMIT DROP AS
    SELECT id FROM training_courses
     WHERE video_duration_seconds IS NOT NULL AND video_duration_seconds < 60
       AND COALESCE(duration_minutes, 0) * 60 >= 4 * video_duration_seconds;

-- Unfinished enrollments whose "video watched" rests on the forged length
-- (less than a minute credited) must watch again; finished courses are kept.
UPDATE training_enrollments e SET video_completed = 0
  FROM _tc_forged f
 WHERE e.course_id = f.id AND COALESCE(e.video_completed, 0) = 1
   AND COALESCE(e.status, '') <> 'completed' AND COALESCE(e.watched_seconds, 0) < 60;

UPDATE training_courses c SET video_duration_seconds = NULL FROM _tc_forged f WHERE c.id = f.id;
COMMIT;
