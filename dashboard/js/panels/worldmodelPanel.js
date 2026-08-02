/**
 * World Model Panel
 * Displays the interpreted brain state: sensed + evaluated + decided
 * Shows the current world model snapshot and trends
 */

class WorldModelPanel extends BasePanel {
    constructor(panelId, config) {
        super(panelId, config);
        this.panelType = 'worldmodel';
        this.worldState = {};
        this.stateHistory = [];
        this.maxHistorySize = 10;
        this.lastDistance = null;
    }

    getTitle() {
        return '🧠 World Model';
    }

    getContentHTML() {
        return `
            <div class="worldmodel-content">
                <div class="state-snapshot">
                    <div class="state-grid">
                        <div class="state-item">
                            <span class="state-label">Distance</span>
                            <span class="state-value distance-value">--</span>
                        </div>
                        <div class="state-item">
                            <span class="state-label">Safety</span>
                            <span class="state-value safety-value">--</span>
                        </div>
                        <div class="state-item">
                            <span class="state-label">Actuator</span>
                            <span class="state-value actuator-value">--</span>
                        </div>
                        <div class="state-item">
                            <span class="state-label">Last Reflex</span>
                            <span class="state-value reflex-value">--</span>
                        </div>
                        <div class="state-item">
                            <span class="state-label">Events</span>
                            <span class="state-value event-count">0</span>
                        </div>
                    </div>
                </div>
                <div class="state-trends">
                    <div class="trend-label">Distance Trend:</div>
                    <div class="trend-indicator">→ STABLE</div>
                </div>
                <div class="state-history">
                    <div class="history-header">State History (Last 5)</div>
                    <div class="history-items"></div>
                </div>
            </div>
        `;
    }

    onRender() {
        this.updateDisplay();
    }

    onUpdate(event) {
        // event.type is the wire type ("world_model_update"), not the short
        // internal channel name ("worldmodel") — this used to check the
        // latter and so always bailed here, leaving the panel stuck on "--"
        // even though routing (now fixed) was correctly reaching it.
        if (event.type !== 'world_model_update') return;

        const {
            distance_cm,
            safe,
            actuator_state,
            last_reflex,
            total_events,
            timestamp
        } = event.data;

        // Store world state
        this.worldState = {
            distance_cm,
            safe,
            actuator_state,
            last_reflex,
            total_events,
            timestamp
        };

        // Track history
        this.stateHistory.unshift({
            distance_cm,
            safe,
            actuator_state,
            timestamp,
            trend: this.calculateTrend(distance_cm)
        });
        if (this.stateHistory.length > this.maxHistorySize) {
            this.stateHistory.pop();
        }

        this.lastDistance = distance_cm;
        this.updateDisplay();
        this.setStatus('active');
    }

    updateDisplay() {
        const { distance_cm, safe, actuator_state, last_reflex, total_events } = this.worldState;

        // Update distance
        const distanceEl = this.element.querySelector('.distance-value');
        if (distanceEl && distance_cm !== undefined) {
            distanceEl.textContent = distance_cm.toFixed(1) + ' cm';
        }

        // Update safety
        const safetyEl = this.element.querySelector('.safety-value');
        if (safetyEl) {
            safetyEl.textContent = safe ? '✓ SAFE' : '⚠ DANGER';
            safetyEl.className = `state-value safety-value ${safe ? 'safe' : 'danger'}`;
        }

        // Update actuator state
        const actuatorEl = this.element.querySelector('.actuator-value');
        if (actuatorEl && actuator_state) {
            actuatorEl.textContent = actuator_state;
        }

        // Update last reflex
        const reflexEl = this.element.querySelector('.reflex-value');
        if (reflexEl && last_reflex) {
            reflexEl.textContent = last_reflex || 'none';
        }

        // Update event count
        const countEl = this.element.querySelector('.event-count');
        if (countEl && total_events) {
            countEl.textContent = total_events;
        }

        // Update trends
        this.updateTrends();

        // Update history
        this.updateHistory();
    }

    updateTrends() {
        const trendEl = this.element.querySelector('.trend-indicator');
        if (!trendEl || !this.worldState.distance_cm) return;

        const current = this.worldState.distance_cm;
        const previous = this.stateHistory[1]?.distance_cm;

        let trendText = '→ STABLE';
        let trendColor = '#888';

        if (previous !== undefined) {
            if (current < previous) {
                trendText = '↗ CLOSER';
                trendColor = '#ff6600';
            } else if (current > previous) {
                trendText = '↘ FARTHER';
                trendColor = '#0088ff';
            }
        }

        trendEl.textContent = trendText;
        trendEl.style.color = trendColor;
    }

    updateHistory() {
        const historyContainer = this.element.querySelector('.history-items');
        if (!historyContainer) return;

        historyContainer.innerHTML = this.stateHistory.slice(0, 5).map((entry, idx) => {
            const time = new Date(entry.timestamp).toLocaleTimeString();
            const safeClass = entry.safe ? 'safe' : 'danger';
            return `
                <div class="history-item">
                    <span class="history-distance">${entry.distance_cm.toFixed(1)}cm</span>
                    <span class="history-state" style="color: ${entry.safe ? '#00ff00' : '#ff3333'}">
                        ${entry.safe ? '✓' : '⚠'}
                    </span>
                    <span class="history-time">${time}</span>
                </div>
            `;
        }).join('');
    }

    calculateTrend(currentDistance) {
        if (this.lastDistance === null) return 'new';
        if (currentDistance < this.lastDistance) return 'closer';
        if (currentDistance > this.lastDistance) return 'farther';
        return 'stable';
    }
}

// Export for use in browser
window.WorldModelPanel = WorldModelPanel;
