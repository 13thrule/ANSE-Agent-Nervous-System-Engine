/**
 * Reflex Panel
 * Displays triggered reflexes and their conditions
 */

class ReflexPanel extends BasePanel {
    constructor(panelId, config) {
        super(panelId, config);
        this.panelType = 'reflex';
        this.activeReflexes = new Map();
        this.reflexHistory = [];
        this.maxHistorySize = 50;
    }

    getTitle() {
        return '⚡ Reflexes Triggered';
    }

    getContentHTML() {
        return `
            <div class="reflex-content">
                <div class="active-reflexes">
                    <div class="reflexes-header">Active</div>
                    <div class="reflexes-list" id="active-reflexes-list">
                        <div class="empty-state">No active reflexes</div>
                    </div>
                </div>
                <div class="reflex-history">
                    <div class="history-header">Recent Triggers</div>
                    <div class="history-list" id="reflex-history-list"></div>
                </div>
            </div>
        `;
    }

    onRender() {
        this.updateDisplay();
    }

    onUpdate(event) {
        // Same wire-type-vs-channel-name mismatch as worldmodelPanel.js.
        if (event.type !== 'reflex_event') return;

        const { reflex_name, condition, triggered, timestamp } = event.data;

        if (triggered) {
            // Reflex triggered
            this.activeReflexes.set(reflex_name, {
                name: reflex_name,
                condition,
                triggeredAt: timestamp,
                count: (this.activeReflexes.get(reflex_name)?.count || 0) + 1
            });
        } else {
            // Reflex cleared
            this.activeReflexes.delete(reflex_name);
        }

        // Add to history
        this.reflexHistory.unshift({
            reflex_name,
            condition,
            triggered,
            timestamp
        });
        if (this.reflexHistory.length > this.maxHistorySize) {
            this.reflexHistory.pop();
        }

        this.updateDisplay();
        this.setStatus('active');
    }

    updateDisplay() {
        this.updateActiveReflexes();
        this.updateHistory();
    }

    updateActiveReflexes() {
        const list = this.element.querySelector('#active-reflexes-list');
        if (!list) return;

        if (this.activeReflexes.size === 0) {
            list.innerHTML = '<div class="empty-state">No active reflexes</div>';
            return;
        }

        list.innerHTML = Array.from(this.activeReflexes.values()).map(reflex => {
            const duration = this.calculateDuration(reflex.triggeredAt);
            return `
                <div class="reflex-item active">
                    <span class="reflex-name">${this.formatName(reflex.name)}</span>
                    <span class="reflex-condition">${reflex.condition || 'condition'}</span>
                    <span class="reflex-count">×${reflex.count}</span>
                    <span class="reflex-duration">${duration}s</span>
                </div>
            `;
        }).join('');
    }

    updateHistory() {
        const list = this.element.querySelector('#reflex-history-list');
        if (!list) return;

        list.innerHTML = this.reflexHistory.slice(0, 10).map(entry => {
            const time = new Date(entry.timestamp).toLocaleTimeString();
            const status = entry.triggered ? 'triggered' : 'cleared';
            return `
                <div class="reflex-history-item ${status}">
                    <span class="history-bullet">${entry.triggered ? '⚡' : '✓'}</span>
                    <span class="history-name">${this.formatName(entry.reflex_name)}</span>
                    <span class="history-time">${time}</span>
                </div>
            `;
        }).join('');
    }

    calculateDuration(timestamp) {
        const start = new Date(timestamp);
        const now = new Date();
        return Math.floor((now - start) / 1000);
    }

    formatName(name) {
        return name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    }
}

// Export for use in browser
window.ReflexPanel = ReflexPanel;
