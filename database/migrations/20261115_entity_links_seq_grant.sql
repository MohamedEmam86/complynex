-- build_entity_links.py resets the cluster id sequence (setval) on every rebuild: needs UPDATE on it
GRANT USAGE, SELECT, UPDATE ON SEQUENCE screening_entity_clusters_id_seq TO complynex;
