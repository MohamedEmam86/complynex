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
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class TransactionAnalyzer:
    """
    Analyzes customer transactions for potential AML risks:
    1. Velocity: High frequency of transactions in a short period.
    2. Structuring (Smurfing): Multiple transactions just below a reporting threshold.
    3. Large Transactions: Transactions exceeding a specific amount.
    """
    
    def __init__(self, reporting_threshold=10000.0, velocity_limit_count=5, velocity_window_days=1):
        self.reporting_threshold = reporting_threshold
        self.velocity_limit_count = velocity_limit_count
        self.velocity_window_days = velocity_window_days

    def analyze_transactions(self, customer_id, transactions):
        """
        Analyze a list of transactions for a customer.
        transactions: list of dicts {'amount': float, 'timestamp': datetime, 'id': str}
        Returns a list of alerts.
        """
        alerts = []
        
        if not transactions:
            return alerts
            
        # Ensure timestamps are datetime objects if strings
        for tx in transactions:
            if isinstance(tx['timestamp'], str):
                try:
                    tx['timestamp'] = datetime.fromisoformat(tx['timestamp'].replace('Z', '+00:00'))
                except ValueError:
                    logger.warning(f"Invalid timestamp format: {tx['timestamp']}")

        # Sort transactions by date (descending)
        sorted_txs = sorted(transactions, key=lambda x: x['timestamp'], reverse=True)
        
        # 1. Velocity Checks
        now = datetime.now()
        window_start = now - timedelta(days=self.velocity_window_days)
        recent_txs = [tx for tx in sorted_txs if tx['timestamp'] >= window_start]
        
        if len(recent_txs) >= self.velocity_limit_count:
            alerts.append({
                'type': 'VELOCITY_ALERT',
                'severity': 'MEDIUM',
                'description': f"High transaction frequency: {len(recent_txs)} transactions in {self.velocity_window_days} day(s).",
                'details': {
                    'count': len(recent_txs),
                    'limit': self.velocity_limit_count,
                    'window_days': self.velocity_window_days
                }
            })
            
        # 2. Structuring Checks (Smurfing)
        # Look for several transactions just below the threshold (e.g. 90% - 100% of threshold)
        lower_bound = self.reporting_threshold * 0.9
        structuring_txs = [tx for tx in sorted_txs if lower_bound <= tx['amount'] < self.reporting_threshold]
        
        if len(structuring_txs) >= 3:
            alerts.append({
                'type': 'STRUCTURING_ALERT',
                'severity': 'HIGH',
                'description': f"Potential structuring detected: {len(structuring_txs)} transactions just below the {self.reporting_threshold} threshold.",
                'details': {
                    'detected_count': len(structuring_txs),
                    'threshold': self.reporting_threshold,
                    'range': f"{lower_bound} - {self.reporting_threshold}"
                }
            })
            
        # 3. Large Transaction Check
        large_txs = [tx for tx in sorted_txs if tx['amount'] >= self.reporting_threshold]
        if large_txs:
             alerts.append({
                'type': 'LARGE_TRANSACTION_ALERT',
                'severity': 'LOW',
                'description': f"Customer conducted {len(large_txs)} transaction(s) exceeding reporting threshold ({self.reporting_threshold}).",
                'details': {
                    'count': len(large_txs),
                    'threshold': self.reporting_threshold,
                    'max_amount': max(tx['amount'] for tx in large_txs)
                }
            })
            
        return alerts

    def get_summary_stats(self, transactions):
        """Helper to get summary stats for a customer"""
        if not transactions:
            return {'count': 0, 'total': 0.0, 'avg': 0.0}
            
        total = sum(tx['amount'] for tx in transactions)
        return {
            'count': len(transactions),
            'total': total,
            'avg': total / len(transactions),
            'max': max(tx['amount'] for tx in transactions)
        }
