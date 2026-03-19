document.addEventListener('DOMContentLoaded', () => {
    const queryForm = document.getElementById('query-form');
    const questionInput = document.getElementById('question');
    const resultsArea = document.getElementById('results-area');
    const answerText = document.getElementById('answer-text');
    const sourcesList = document.getElementById('sources-list');
    
    const refreshStatsBtn = document.getElementById('refresh-stats');
    const statCount = document.getElementById('stat-count');
    const statLlm = document.getElementById('stat-llm');
    const statLastSync = document.getElementById('stat-last-sync');
    
    const kSlider = document.getElementById('k-slider');
    const kValueDisplay = document.getElementById('k-value');

    // --- Tabs Handling ---
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            // Remove active classes
            tabButtons.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            // Add active class to clicked tab and target
            btn.classList.add('active');
            const targetId = btn.getAttribute('data-tab');
            document.getElementById(targetId).classList.add('active');
        });
    });

    // --- Slider sync ---
    kSlider.addEventListener('input', () => {
        kValueDisplay.innerText = kSlider.value;
    });

    // --- Query Handling ---
    queryForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const question = questionInput.value.trim();
        if (!question) return;

        // UI Feedback
        answerText.innerHTML = '<em>Analyzing...</em>';
        document.getElementById('sources-body').innerHTML = '';
        resultsArea.classList.remove('hidden');
        questionInput.disabled = true;

        const top_k = parseInt(kSlider.value);

        try {
            const response = await fetch('/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question, top_k })
            });

            if (response.status === 501) {
                answerText.innerText = "Error 501: RAG service is not implemented yet.";
            } else {
                const data = await response.json();
                answerText.innerText = data.answer || "Could not process the response.";
                
                const sourcesBody = document.getElementById('sources-body');
                if (data.sources && data.sources.length > 0) {
                    data.sources.forEach(post => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td class="source-author">@${post.author_handle}</td>
                            <td class="source-text">${post.text}</td>
                        `;
                        sourcesBody.appendChild(tr);
                    });
                }
            }
        } catch (error) {
            console.error('Error fetching query:', error);
            answerText.innerText = "Error: Could not connect to the server.";
        } finally {
            questionInput.disabled = false;
        }
    });

    let historyChartInstance = null;
    let currentHistoryData = null;
    let currentView = 'percentage'; // 'percentage' or 'volume'

    const renderChart = (data) => {
        const ctx = document.getElementById('historyChart').getContext('2d');
        if (historyChartInstance) {
            historyChartInstance.destroy();
        }

        let chartData = {};
        let options = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'top' }
            },
            scales: {
                y: { 
                    beginAtZero: true,
                    title: { display: true, text: currentView === 'percentage' ? 'Percentage (%)' : 'Number of Posts' }
                }
            }
        };

        if (currentView === 'percentage') {
            chartData = {
                labels: data.labels,
                datasets: [{
                    label: '% Real Misogyny (BERT)',
                    data: data.percentage,
                    borderColor: '#1a1a1a',
                    backgroundColor: 'rgba(26, 26, 26, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                }]
            };
            options.scales.y.max = 100;
        } else {
            chartData = {
                labels: data.labels,
                datasets: [
                    {
                        label: 'Misogynistic Posts',
                        data: data.misogynous,
                        borderColor: '#e74c3c',
                        backgroundColor: 'rgba(231, 76, 60, 0.6)',
                        fill: true,
                        tension: 0.3
                    },
                    {
                        label: 'Clean Posts',
                        data: data.clean,
                        borderColor: '#2ecc71',
                        backgroundColor: 'rgba(46, 204, 113, 0.4)',
                        fill: true,
                        tension: 0.3
                    }
                ]
            };
            options.scales.x = { stacked: true };
            options.scales.y.stacked = true;
        }

        historyChartInstance = new Chart(ctx, {
            type: 'line',
            data: chartData,
            options: options
        });
    };

    // --- Stats Handling ---
    const fetchStats = async () => {
        try {
            const [statsRes, histRes] = await Promise.all([
                fetch('/stats'),
                fetch('/stats/history')
            ]);
            
            if (statsRes.status === 501) {
                statCount.innerText = "N/A";
                statLlm.innerText = "Not implemented";
            } else {
                const data = await statsRes.json();
                statCount.innerText = data.indexed_posts || 0;
                statLlm.innerText = data.llm_status || "Unknown";
                statLastSync.innerText = data.last_scrape || "Never";
                
                statLlm.classList.remove('gray');
                statLastSync.classList.remove('gray');
            }
            
            if (histRes.ok) {
                currentHistoryData = await histRes.json();
                renderChart(currentHistoryData);
            }
        } catch (error) {
            console.error('Error fetching stats:', error);
        }
    };

    const viewPercentageBtn = document.getElementById('view-percentage');
    const viewVolumeBtn = document.getElementById('view-volume');

    viewPercentageBtn.addEventListener('click', () => {
        currentView = 'percentage';
        viewPercentageBtn.classList.add('active');
        viewVolumeBtn.classList.remove('active');
        if (currentHistoryData) renderChart(currentHistoryData);
    });

    viewVolumeBtn.addEventListener('click', () => {
        currentView = 'volume';
        viewVolumeBtn.classList.add('active');
        viewPercentageBtn.classList.remove('active');
        if (currentHistoryData) renderChart(currentHistoryData);
    });

    refreshStatsBtn.addEventListener('click', fetchStats);

    // Initial load
    fetchStats();
});
