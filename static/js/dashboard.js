document.addEventListener('DOMContentLoaded', () => {
    fetchDashboardData();
});

async function fetchDashboardData() {
    try {
        const response = await fetch('/api/v1/analytics/summary');
        let data;
        if (response.ok) {
            data = await response.json();
        } else {
            console.warn('Failed to fetch from API, using mock data.');
            data = getMockData();
        }
        renderDashboard(data);
    } catch (error) {
        console.error('Error fetching dashboard data:', error);
        renderDashboard(getMockData());
    }
}

function getMockData() {
    return {
        active_tenants: 12,
        total_api_calls: 4521,
        feedback: {
            positive: 85,
            negative: 15,
            total: 100,
            recent: [
                { timestamp: '2026-05-23T10:00:00Z', session_id: 'sess-001', rating: 1, comment: 'Great recommendations!' },
                { timestamp: '2026-05-23T09:30:00Z', session_id: 'sess-002', rating: -1, comment: 'A bit slow.' },
                { timestamp: '2026-05-22T14:20:00Z', session_id: 'sess-003', rating: 1, comment: 'Spot on.' }
            ]
        },
        api_trend: {
            labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            data: [120, 190, 300, 250, 400, 450, 500]
        }
    };
}

function renderDashboard(data) {
    // Update KPIs
    document.getElementById('kpi-tenants').innerText = data.active_tenants;
    document.getElementById('kpi-api-calls').innerText = data.total_api_calls;
    
    const feedbackPercent = data.feedback.total > 0 
        ? Math.round((data.feedback.positive / data.feedback.total) * 100) 
        : 0;
    document.getElementById('kpi-feedback').innerText = `${feedbackPercent}%`;

    // Render Chart
    const ctx = document.getElementById('apiUsageChart').getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.api_trend.labels,
            datasets: [{
                label: 'API Calls',
                data: data.api_trend.data,
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: '#f8fafc' }
                }
            },
            scales: {
                x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' }, beginAtZero: true }
            }
        }
    });

    // Render Table
    const tbody = document.getElementById('feedback-tbody');
    tbody.innerHTML = '';
    data.feedback.recent.forEach(f => {
        const tr = document.createElement('tr');
        const ratingIcon = f.rating > 0 ? '👍' : '👎';
        const date = new Date(f.timestamp).toLocaleString();
        
        tr.innerHTML = `
            <td>${date}</td>
            <td>${f.session_id}</td>
            <td>${ratingIcon}</td>
            <td>${f.comment || '-'}</td>
        `;
        tbody.appendChild(tr);
    });
}
