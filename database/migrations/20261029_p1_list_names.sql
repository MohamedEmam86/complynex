-- Phase 1: the EMLCU row was labelled as a PEP list; it is the Egyptian local terrorist lists.
UPDATE sanctions_lists SET list_name = 'EMLCU Egyptian Terrorist Lists' WHERE list_code = 'emlcu' AND list_name = 'Egypt PEP List (Manual)';
