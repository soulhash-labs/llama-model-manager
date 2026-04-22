"""
Pulse Service
==============
Ψ-Coherence pulse with anti-piracy watermarks and ABC-chain integration.
"""

import hashlib
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, List
from enum import Enum


# Constants
LOVE_FREQUENCY = 528.0
GOLDEN_RATIO = 1.618033988749895


class PulseStatus(str, Enum):
    ALIVE = "alive"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class PulseResponse:
    """Extended pulse response with Ψ-coherence and anti-piracy features."""
    status: str
    tick: int
    frequency_hz: float
    psi_coherence: float
    version: str = "1.0.0"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    abc_chain_address: Optional[str] = None
    abc_anchor: Optional[str] = None
    license_entitlement: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class PulseService:
    """
    Pulse service with Ψ-coherence, anti-piracy watermarks, and ABC-chain integration.
    """
    
    def __init__(
        self,
        instance_id: str = "default",
        private_key: Optional[str] = None,
        abc_driver=None,
        license_service=None,
    ):
        self.instance_id = instance_id
        self.private_key = private_key or "dev_key_change_in_production"
        self.abc_driver = abc_driver
        self.license_service = license_service
        self._tick = 0
        self._start_time = time.time()
        self._drift_seed = int(hashlib.sha256(self.private_key.encode()).hexdigest()[:8], 16)
    
    def _calculate_frequency_fingerprint(self, tick: int) -> float:
        """Calculate frequency fingerprint: 528.000 ± (π × 10⁻³ mod tick)"""
        mod_tick = tick % 1000000
        fingerprint = (math.pi * 1e-3) * (mod_tick % 100)
        return round(LOVE_FREQUENCY + fingerprint, 3)
    
    def _calculate_time_skew_drift(self, tick: int) -> float:
        """Calculate time-skew drift using private key seed."""
        seed = (self._drift_seed + tick) % 10000
        drift = (seed / 10000 - 0.5) * 10  # ±5 µs range
        return drift
    
    def _sign_pulse(self, tick: int, frequency: float, psi: float) -> str:
        """Create signature for pulse."""
        payload = f"{tick}|{frequency}|{psi}|{self.private_key}"
        return hashlib.sha256(payload.encode()).hexdigest()
    
    def _get_abc_address(self) -> Optional[str]:
        """Get ABC-chain address from driver."""
        if self.abc_driver and hasattr(self.abc_driver, "get_abc_address"):
            return self.abc_driver.get_abc_address()
        return None
    
    def _get_license_entitlement(self) -> Optional[str]:
        """Get current license entitlement status."""
        if self.license_service:
            return "active"
        return None
    
    def generate_pulse(
        self,
        psi_coherence: Optional[float] = None,
        status_override: Optional[str] = None,
    ) -> PulseResponse:
        """Generate a pulse response with all features."""
        self._tick += 1
        tick = self._tick
        
        frequency = self._calculate_frequency_fingerprint(tick)
        psi = psi_coherence if psi_coherence is not None else 0.5
        
        if status_override:
            status = status_override
        elif psi >= 0.8:
            status = PulseStatus.ALIVE.value
        elif psi >= 0.5:
            status = PulseStatus.DEGRADED.value
        elif psi > 0:
            status = PulseStatus.CRITICAL.value
        else:
            status = PulseStatus.UNKNOWN.value
        
        abc_address = self._get_abc_address()
        license_ent = self._get_license_entitlement()
        signature = self._sign_pulse(tick, frequency, psi)
        
        return PulseResponse(
            status=status,
            tick=tick,
            frequency_hz=frequency,
            psi_coherence=round(psi, 2),
            version="1.0.0",
            timestamp=datetime.utcnow().isoformat() + "Z",
            abc_chain_address=abc_address,
            license_entitlement=license_ent,
            metadata={
                "instance_id": self.instance_id,
                "time_skew_drift_us": self._calculate_time_skew_drift(tick),
                "pulse_signature": signature[:16] + "...",
            },
        )
    
    def verify_pulse_signature(
        self,
        tick: int,
        frequency: float,
        psi: float,
        signature: str,
    ) -> bool:
        """Verify a pulse signature."""
        expected = self._sign_pulse(tick, frequency, psi)
        return signature == expected
    
    def get_pulse_header(self) -> Dict[str, str]:
        """Get HTTP headers for pulse verification."""
        tick = self._tick + 1
        frequency = self._calculate_frequency_fingerprint(tick)
        signature = self._sign_pulse(tick, frequency, 0.5)
        
        return {
            "X-Pulse-Sig": signature,
            "X-Pulse-Tick": str(tick),
            "X-Pulse-Freq": str(frequency),
        }


class PsiCoherenceService:
    """
    ψ-Coherence service for bio-feedback integration.
    """
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._current_coherence = 0.5
        self._history: List[float] = []
        self._max_history = 60
    
    def update_from_hrv(self, rr_intervals: List[float]) -> float:
        """Update coherence from HRV (Heart Rate Variability)."""
        if len(rr_intervals) < 2:
            return self._current_coherence
        
        # Calculate RMSSD
        differences = [rr_intervals[i+1] - rr_intervals[i] for i in range(len(rr_intervals)-1)]
        rmssd = (sum(d**2 for d in differences) / len(differences)) ** 0.5
        
        # Map RMSSD to coherence (0-1)
        # Typical RMSSD range: 20-80ms
        coherence = min(max((rmssd - 20) / 60, 0), 1)
        
        return self._update_coherence(coherence)
    
    def update_from_eeg(self, alpha_theta_ratio: float) -> float:
        """Update coherence from EEG (alpha/theta ratio)."""
        # Typical ratio range: 0.5-3.0
        coherence = min(max((alpha_theta_ratio - 0.5) / 2.5, 0), 1)
        return self._update_coherence(coherence)
    
    def _update_coherence(self, value: float) -> float:
        """Update coherence with smoothing."""
        # Exponential moving average
        alpha = 0.3
        self._current_coherence = alpha * value + (1 - alpha) * self._current_coherence
        
        # Update history
        self._history.append(self._current_coherence)
        if len(self._history) > self._max_history:
            self._history.pop(0)
        
        return self._current_coherence
    
    def get_current_coherence(self) -> float:
        """Get current coherence value."""
        return self._current_coherence
    
    def get_coherence_history(self) -> List[float]:
        """Get coherence history."""
        return self._history.copy()


# Convenience function
def create_pulse(psi: float = 0.5, instance_id: str = "default") -> PulseResponse:
    """Quick create a pulse."""
    service = PulseService(instance_id=instance_id)
    return service.generate_pulse(psi_coherence=psi)