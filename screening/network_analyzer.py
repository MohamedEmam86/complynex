# =============================================================================
# Copyright (c) 2026 ComplyNex (complynex.online) — All Rights Reserved.
#
# This software is the proprietary and confidential intellectual property of
# ComplyNex (complynex.online), owned by Mohamed Emam.
# Unauthorized copying, reproduction, modification,
# distribution, reverse engineering, or use of this software, in whole or in
# part, via any medium, is strictly prohibited without prior written
# permission from the owner.
#
# Owner and Author: Mohamed Emam — GRC & Compliance Expert
# Contact: f.mohemam85@gmail.com | admin@complynex.online
#
# Registered deployment: complynex.online
# ComplyNex Full Compliance Platform (CMS) — Proprietary & Confidential
# =============================================================================

import logging
import os

logger = logging.getLogger(__name__)

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

class NetworkAnalyzer:
    """
    Analyzes entity relationships using Neo4j Graph Database.
    Detects hidden connections, circular ownership, and proximity to sanctioned entities.
    """
    
    def __init__(self, uri=None, user=None, password=None):
        self.driver = None
        self.enabled = False
        
        # Use env vars or provided args
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "password")
        
        if GraphDatabase:
            try:
                self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
                self.driver.verify_connectivity()
                self.enabled = True
                logger.info("Connected to Neo4j Graph Database.")
            except Exception as e:
                logger.debug(f"Could not connect to Neo4j: {e}. Network analysis disabled. (Normal if Neo4j not running)")
        else:
            logger.debug("neo4j module not found. Network analysis disabled.")

    def close(self):
        if self.driver:
            self.driver.close()

    def sync_entity(self, entity_id, name, entity_type, risk_score):
        """
        Syncs a screening entity to the Graph.
        """
        if not self.enabled: return
        
        query = """
        MERGE (e:Entity {id: $id})
        SET e.name = $name, 
            e.type = $type,
            e.risk_score = $score,
            e.last_updated = timestamp()
        """
        try:
            with self.driver.session() as session:
                session.run(query, id=str(entity_id), name=name, type=entity_type, score=risk_score)
        except Exception as e:
            logger.error(f"Failed to sync entity to graph: {e}")

    def create_relationship(self, source_id, target_id, rel_type, properties=None):
        """
        Creates a relationship between two entities.
        rel_type: OWNERSHIP, MANAGES, FAMILY, TRANSACTION
        """
        if not self.enabled: return
        
        props_str = ""
        if properties:
            # Simple property serialization for Cypher (be careful with injection if not parameterized properly)
            # using params is safer
            pass

        query = f"""
        MATCH (a:Entity {{id: $source_id}})
        MATCH (b:Entity {{id: $target_id}})
        MERGE (a)-[r:{rel_type}]->(b)
        SET r += $props
        """
        try:
            with self.driver.session() as session:
                session.run(query, source_id=str(source_id), target_id=str(target_id), props=properties or {})
        except Exception as e:
            logger.error(f"Failed to create relationship: {e}")

    def detect_hidden_risk(self, entity_id, max_hops=3):
        """
        Finds shortest paths to high-risk entities.
        Returns: List of paths with risk > threshold.
        """
        if not self.enabled: return []

        query = """
        MATCH path = shortestPath((start:Entity {id: $id})-[*..%d]-(end:Entity))
        WHERE end.risk_score >= 90 AND start <> end
        RETURN path, end.risk_score, length(path) as hops
        ORDER BY end.risk_score DESC, hops ASC
        LIMIT 5
        """ % max_hops
        
        results = []
        try:
            with self.driver.session() as session:
                result = session.run(query, id=str(entity_id))
                for record in result:
                    # Simplify path for reporting
                    path = record["path"]
                    results.append({
                        "target_risk": record["end.risk_score"],
                        "hops": record["hops"],
                        "path_description": f"Connected to {path.end['name']} ({path.end['type']})"
                    })
        except Exception as e:
            logger.error(f"Graph analysis failed: {e}")
            
        return results
