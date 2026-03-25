document.addEventListener('DOMContentLoaded', () => {
    const queryForm = document.getElementById('query-form');
    const questionInput = document.getElementById('question');
    const resultsArea = document.getElementById('results-area');
    const answerText = document.getElementById('answer-text');
    const sourcesList = document.getElementById('sources-list');
    
    const refreshStatsBtn = document.getElementById('refresh-stats');
    const statCount = document.getElementById('stat-count');
    const statProfiles = document.getElementById('stat-profiles');
    const statToxicity = document.getElementById('stat-toxicity');
    
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

        // Sparse labels: show ~25 labels across the timeline
        const step = Math.max(1, Math.floor(data.labels.length / 25));

        const commonOptions = {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            onClick: (e, activeElements) => {
                if (activeElements.length > 0) {
                    const dataIndex = activeElements[0].index;
                    const clickedLabel = data.labels[dataIndex];
                    fetchDrilldownData(clickedLabel);
                }
            },
            plugins: {
                legend: {
                    position: 'top',
                    align: 'end',
                    labels: {
                        font: { family: "'Inter', sans-serif", size: 12, weight: '500' },
                        color: '#888',
                        usePointStyle: true,
                        pointStyle: 'circle',
                        padding: 20,
                        boxWidth: 8
                    }
                },
                tooltip: {
                    backgroundColor: '#1a1a1a',
                    titleFont: { family: "'Inter', sans-serif", size: 13, weight: '600' },
                    bodyFont: { family: "'Inter', sans-serif", size: 12 },
                    padding: 14,
                    cornerRadius: 8,
                    displayColors: true,
                    boxPadding: 6,
                    caretSize: 6
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    border: { display: false },
                    ticks: {
                        font: { family: "'Inter', sans-serif", size: 11 },
                        color: '#aaa',
                        maxRotation: 45,
                        minRotation: 30,
                        callback: function(value, index) {
                            return index % step === 0 ? this.getLabelForValue(value) : '';
                        },
                        autoSkip: false
                    }
                },
                y: {
                    beginAtZero: true,
                    border: { display: false },
                    grid: {
                        color: 'rgba(0,0,0,0.04)',
                        drawTicks: false
                    },
                    ticks: {
                        font: { family: "'Inter', sans-serif", size: 11 },
                        color: '#aaa',
                        padding: 10
                    },
                    title: {
                        display: true,
                        text: currentView === 'percentage' ? 'Misogyny Score (%)' : 'Number of Posts',
                        font: { family: "'Inter', sans-serif", size: 12, weight: '600' },
                        color: '#888',
                        padding: { bottom: 10 }
                    }
                }
            }
        };

        let chartData = {};

        if (currentView === 'percentage') {
            // Gradient fill for percentage line
            const gradient = ctx.createLinearGradient(0, 0, 0, ctx.canvas.clientHeight);
            gradient.addColorStop(0, 'rgba(30, 30, 30, 0.15)');
            gradient.addColorStop(1, 'rgba(30, 30, 30, 0.0)');

            chartData = {
                labels: data.labels,
                datasets: [
                    {
                        label: 'Qwen Misogyny (%)',
                        data: data.qwen_percentage,
                        borderColor: '#6f42c1',
                        backgroundColor: 'rgba(111, 66, 193, 0.05)',
                        borderWidth: 2.5,
                        fill: true,
                        tension: 0.35,
                        pointRadius: 0,
                        pointHoverRadius: 5,
                        pointHoverBackgroundColor: '#6f42c1',
                        pointHoverBorderColor: '#fff',
                        pointHoverBorderWidth: 2
                    }
                ]
            };
        } else {
            // Gradients for volume view
            const gradientRed = ctx.createLinearGradient(0, 0, 0, ctx.canvas.clientHeight);
            gradientRed.addColorStop(0, 'rgba(220, 53, 69, 0.35)');
            gradientRed.addColorStop(1, 'rgba(220, 53, 69, 0.02)');

            const gradientGreen = ctx.createLinearGradient(0, 0, 0, ctx.canvas.clientHeight);
            gradientGreen.addColorStop(0, 'rgba(40, 167, 69, 0.25)');
            gradientGreen.addColorStop(1, 'rgba(40, 167, 69, 0.02)');

            chartData = {
                labels: data.labels,
                datasets: [
                    {
                        label: 'Misogynistic Posts',
                        data: data.qwen_misogynous,
                        borderColor: '#6f42c1',
                        backgroundColor: 'rgba(111, 66, 193, 0.1)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.35,
                        pointRadius: 0,
                        pointHoverRadius: 5,
                        pointHoverBackgroundColor: '#6f42c1',
                        pointHoverBorderColor: '#fff',
                        pointHoverBorderWidth: 2
                    },
                    {
                        label: 'Clean Posts',
                        data: data.clean,
                        borderColor: '#28a745',
                        backgroundColor: gradientGreen,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.35,
                        pointRadius: 0,
                        pointHoverRadius: 5,
                        pointHoverBackgroundColor: '#28a745',
                        pointHoverBorderColor: '#fff',
                        pointHoverBorderWidth: 2
                    }
                ]
            };
        }

        historyChartInstance = new Chart(ctx, {
            type: 'line',
            data: chartData,
            options: commonOptions
        });
    };

    // --- Risk Monitor Handling ---
    const riskBody = document.getElementById('risk-body');
    const userModal = document.getElementById('user-modal');
    const userPostsBody = document.getElementById('user-posts-body');
    const modalTitle = document.getElementById('modal-title');
    const modalStats = document.getElementById('modal-stats');
    const closeModal = document.getElementById('close-modal');

    const fetchRiskyUsers = async (mode = 'volume') => {
        try {
            const endpoint = mode === 'diversity' ? '/stats/risky-users-diverse' : '/stats/risky-users';
            const response = await fetch(endpoint);
            const users = await response.json();
            
            // Update table headers based on mode
            const colCount = document.getElementById('risk-col-count');
            const colExtra = document.getElementById('risk-col-extra');
            const modeDesc = document.getElementById('risk-mode-desc');
            
            if (mode === 'diversity') {
                colCount.textContent = 'Unique Posts';
                colExtra.textContent = 'Diversity %';
                modeDesc.textContent = 'Ranked by unique misogynistic posts × severity. Filters out copy-paste spam bots.';
            } else {
                colCount.textContent = 'Misogynistic Posts';
                colExtra.textContent = 'Risk Level';
                modeDesc.textContent = 'Ranked by total misogynistic posts × average severity score. Includes repeated content.';
            }
            
            riskBody.innerHTML = '';
            users.forEach(user => {
                const tr = document.createElement('tr');
                
                if (mode === 'diversity') {
                    const divRatio = user.diversity_ratio || 0;
                    const divColor = divRatio > 80 ? '#28a745' : divRatio > 50 ? '#f0ad4e' : '#dc3545';
                    tr.innerHTML = `
                        <td class="clickable h-link" data-handle="${user._id}">@${user._id}</td>
                        <td>${user.unique_count || 0} <span style="color:#aaa;font-size:0.8em">/ ${user.total_misogynistic_posts}</span></td>
                        <td><span style="color:${divColor};font-weight:700;">${divRatio}%</span></td>
                        <td><button class="view-btn" data-handle="${user._id}">INVESTIGATE</button></td>
                    `;
                } else {
                    const riskLevel = user.risk_score > 5 ? 'High' : (user.risk_score > 1 ? 'Moderate' : 'Low');
                    const riskClass = riskLevel.toLowerCase();
                    tr.innerHTML = `
                        <td class="clickable h-link" data-handle="${user._id}">@${user._id}</td>
                        <td>${user.total_misogynistic_posts}</td>
                        <td><span class="badge badge-${riskClass}">${riskLevel}</span></td>
                        <td><button class="view-btn" data-handle="${user._id}">INVESTIGATE</button></td>
                    `;
                }
                riskBody.appendChild(tr);
            });

            // Add click listeners
            document.querySelectorAll('.view-btn, .h-link').forEach(el => {
                el.addEventListener('click', () => showUserDetails(el.getAttribute('data-handle')));
            });

        } catch (error) {
            console.error('Error fetching risky users:', error);
        }
    };
    
    // Risk mode toggle handlers
    let currentRiskMode = 'volume';
    document.querySelectorAll('.risk-mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            currentRiskMode = btn.dataset.riskMode;
            document.querySelectorAll('.risk-mode-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            fetchRiskyUsers(currentRiskMode);
        });
    });

    const showUserDetails = async (handle) => {
        try {
            const response = await fetch(`/api/user-posts/${handle}`);
            const data = await response.json();
            
            modalTitle.innerText = `Detailed Profile: @${handle}`;
            modalStats.innerHTML = `
                <div class="m-stat"><span>Total Posts:</span> ${data.summary.total_posts}</div>
                <div class="m-stat"><span>Misogynistic:</span> ${data.summary.misogynous_posts}</div>
            `;
            
            userPostsBody.innerHTML = '';
            data.posts.forEach(post => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td class="date-cell">${new Date(post.created_at).toLocaleDateString()}</td>
                    <td class="text-cell">${post.text}</td>
                `;
                userPostsBody.appendChild(tr);
            });
            
            userModal.classList.remove('hidden');
        } catch (error) {
            console.error('Error fetching user details:', error);
        }
    };

    closeModal.addEventListener('click', () => userModal.classList.add('hidden'));
    window.addEventListener('click', (e) => {
        if (e.target === userModal) userModal.classList.add('hidden');
    });

    // --- Stats Handling ---
    let currentHistoryData180d = null;
    let currentHistoryData96h = null;
    let currentTimeMode = '180d'; // '180d' or '96h'

    const fetchStats = async () => {
        try {
            const [statsRes, histRes, histHourlyRes] = await Promise.all([
                fetch('/stats'),
                fetch('/stats/history'),
                fetch('/stats/history-hourly')
            ]);
            
            if (statsRes.status === 501) {
                statCount.innerText = "N/A";
                statProfiles.innerText = "N/A";
                statToxicity.innerText = "N/A";
            } else {
                const data = await statsRes.json();
                statCount.innerText = data.indexed_posts || 0;
                statProfiles.innerText = data.profiles_monitored || 0;
                statToxicity.innerText = `${data.toxicity_rate}`;
            }
            
            if (histRes.ok) {
                currentHistoryData180d = await histRes.json();
            }
            if (histHourlyRes.ok) {
                currentHistoryData96h = await histHourlyRes.json();
            }

            // Render active chart
            updateChartDisplay();

            // Also reload risky users
            fetchRiskyUsers();

        } catch (error) {
            console.error('Error fetching stats:', error);
        }
    };

    const updateChartDisplay = () => {
        const activeData = currentTimeMode === '180d' ? currentHistoryData180d : currentHistoryData96h;
        if (activeData) {
            renderChart(activeData);
        }
    };

    // Metric views
    const viewPercentageBtn = document.getElementById('view-percentage');
    const viewVolumeBtn = document.getElementById('view-volume');

    viewPercentageBtn.addEventListener('click', () => {
        currentView = 'percentage';
        viewPercentageBtn.classList.add('active');
        viewVolumeBtn.classList.remove('active');
        updateChartDisplay();
    });

    viewVolumeBtn.addEventListener('click', () => {
        currentView = 'volume';
        viewVolumeBtn.classList.add('active');
        viewPercentageBtn.classList.remove('active');
        updateChartDisplay();
    });

    // Time ranges
    const time180dBtn = document.getElementById('time-180d');
    const time96hBtn = document.getElementById('time-96h');

    time180dBtn.addEventListener('click', () => {
        currentTimeMode = '180d';
        time180dBtn.classList.add('active');
        time96hBtn.classList.remove('active');
        updateChartDisplay();
    });

    time96hBtn.addEventListener('click', () => {
        currentTimeMode = '96h';
        time96hBtn.classList.add('active');
        time180dBtn.classList.remove('active');
        updateChartDisplay();
    });

    refreshStatsBtn.addEventListener('click', fetchStats);

    // Initial load
    fetchStats();

    // ── Agent Analysis ──────────────────────────────────────────────
    const agentBtn = document.getElementById('agent-analyze-btn');
    const agentHandleInput = document.getElementById('agent-handle');
    const agentLoading = document.getElementById('agent-loading');
    const agentResults = document.getElementById('agent-results');
    const agentTimelineWrapper = document.getElementById('agent-timeline-wrapper');
    const toggleTimelineBtn = document.getElementById('toggle-timeline-btn');
    const progressList = document.getElementById('agent-progress-list');

    if (toggleTimelineBtn && progressList) {
        toggleTimelineBtn.addEventListener('click', () => {
            if (progressList.style.display === 'none') {
                progressList.style.display = 'block';
                toggleTimelineBtn.textContent = 'Hide Steps';
            } else {
                progressList.style.display = 'none';
                toggleTimelineBtn.textContent = 'Show Steps';
            }
        });
    }

    if (agentBtn) {
        agentBtn.addEventListener('click', async () => {
            const handle = agentHandleInput.value.trim().replace(/^@/, '');
            if (!handle) return;

            agentLoading.classList.remove('hidden');
            agentResults.classList.add('hidden');
            
            // Show timeline but hide toggle button while loading
            if (agentTimelineWrapper) agentTimelineWrapper.classList.remove('hidden');
            if (toggleTimelineBtn) toggleTimelineBtn.classList.add('hidden');
            if (progressList) {
                progressList.style.display = 'block';
                progressList.innerHTML = '';
            }

            agentBtn.disabled = true;
            agentBtn.textContent = 'ANALYZING...';

            const addProgressStep = (id, message, emoji, isDone = false, detail = '') => {
                let li = document.getElementById(`step-${id}`);
                
                // If it exists, mark previous steps as done if a new step is coming
                if (!li) {
                    // Mark any currently active item as done
                    document.querySelectorAll('.progress-item.active').forEach(el => {
                        el.classList.remove('active');
                        el.classList.add('done');
                        const statusEl = el.querySelector('.step-status');
                        if (statusEl) statusEl.innerHTML = '✅';
                    });

                    li = document.createElement('li');
                    li.id = `step-${id}`;
                    li.className = 'progress-item active'; // newly added is active
                    progressList.appendChild(li);
                }
                
                if (isDone) {
                    li.className = 'progress-item done';
                }

                li.innerHTML = `
                    <span class="step-emoji">${emoji}</span>
                    <div class="step-content">
                        <span class="step-message">${message}</span>
                        ${detail ? `<span class="step-detail">${detail}</span>` : ''}
                    </div>
                    <span class="step-status">${isDone ? '✅' : '<div class="step-spinner"></div>'}</span>
                `;
                li.scrollIntoView({ behavior: 'smooth', block: 'end' });
            };

            try {
                // Use EventSource for SSE
                const eventSource = new EventSource(`/api/agent-analyze-stream?handle=${encodeURIComponent(handle)}`);

                eventSource.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    
                    if (data.type === 'status') {
                        addProgressStep(data.step, data.message, '🔍', false);
                    } 
                    else if (data.type === 'tool_start') {
                        addProgressStep(data.tool, data.message, data.emoji || '⚙️', false);
                    } 
                    else if (data.type === 'tool_done') {
                        addProgressStep(data.tool, data.message, data.emoji || '✅', true, data.detail);
                    } 
                    else if (data.type === 'result') {
                        eventSource.close();
                        agentLoading.classList.add('hidden');
                        renderAgentResults(data.data);
                        agentBtn.disabled = false;
                        agentBtn.textContent = 'ANALYZE PROFILE';
                        
                        // Re-enable toggle on completion and auto-collapse
                        if (toggleTimelineBtn) {
                            toggleTimelineBtn.classList.remove('hidden');
                            toggleTimelineBtn.textContent = 'Show Steps';
                        }
                        if (progressList) progressList.style.display = 'none';
                        
                    } 
                    else if (data.type === 'error') {
                        eventSource.close();
                        alert('Error: ' + data.message);
                        agentLoading.classList.add('hidden');
                        if (agentTimelineWrapper) agentTimelineWrapper.classList.add('hidden');
                        agentBtn.disabled = false;
                        agentBtn.textContent = 'ANALYZE PROFILE';
                    }
                };

                eventSource.onerror = (err) => {
                    console.error('SSE Error:', err);
                    eventSource.close();
                    // Fallback to traditional alert if it fails immediately, but often happens on finishing
                    // We rely on the 'result' event closing it cleanly.
                };

            } catch (err) {
                console.error('Agent analysis error:', err);
                alert('Error running agent analysis');
                agentLoading.classList.add('hidden');
                if (agentTimelineWrapper) agentTimelineWrapper.classList.add('hidden');
                agentBtn.disabled = false;
                agentBtn.textContent = 'ANALYZE PROFILE';
            }
        });
    }

    const renderAgentResults = (data) => {
        // Verdict badge
        const verdictBadge = document.getElementById('verdict-badge');
        const verdictMap = {
            'GENUINE MISOGYNIST': { cls: 'verdict-danger', label: '⚠ GENUINE MISOGYNIST' },
            'MODERATE RISK': { cls: 'verdict-warning', label: '⚡ MODERATE RISK' },
            'LIKELY FALSE POSITIVE': { cls: 'verdict-safe', label: '✓ LIKELY FALSE POSITIVE' },
            'INCONCLUSIVE': { cls: 'verdict-neutral', label: '? INCONCLUSIVE' }
        };
        const vInfo = verdictMap[data.verdict] || { cls: 'verdict-neutral', label: data.verdict || 'ANALYSIS COMPLETE' };
        verdictBadge.className = 'verdict-badge ' + vInfo.cls;
        verdictBadge.textContent = vInfo.label;

        // Confidence
        const conf = Math.round((data.confidence || 0) * 100);
        document.getElementById('confidence-fill').style.width = conf + '%';
        document.getElementById('confidence-value').textContent = conf + '%';

        // Summary
        document.getElementById('verdict-summary').textContent = data.summary || '';

        // Toxicity ratio
        const ratioEl = document.getElementById('toxicity-ratio');
        ratioEl.textContent = data.toxicity_ratio || '';

        // Card color
        const card = document.getElementById('agent-verdict-card');
        card.className = 'agent-verdict-card ' + vInfo.cls + '-card';

        // ── Categorization bars ──
        const catDiv = document.getElementById('agent-categorization');
        catDiv.innerHTML = '';
        const cat = data.categorization || {};
        const catLabels = {
            hostile: { label: 'Hostile Misogyny', color: '#dc3545', icon: '🔴' },
            benevolent: { label: 'Benevolent Misogyny', color: '#f0ad4e', icon: '🟡' },
            targeted_harassment: { label: 'Targeted Harassment', color: '#e83e8c', icon: '🎯' },
            dogwhistles: { label: 'Dogwhistles', color: '#6f42c1', icon: '🔮' }
        };
        const maxCatVal = Math.max(1, ...Object.values(cat));
        for (const [key, meta] of Object.entries(catLabels)) {
            const val = cat[key] || 0;
            const row = document.createElement('div');
            row.className = 'cat-row';
            row.innerHTML = `
                <span class="cat-label">${meta.icon} ${meta.label}</span>
                <div class="cat-bar-wrapper">
                    <div class="cat-bar-fill" style="width:${(val/maxCatVal)*100}%; background:${meta.color}"></div>
                </div>
                <span class="cat-count">${val}</span>
            `;
            catDiv.appendChild(row);
        }

        // Patterns
        const patternsDiv = document.getElementById('agent-patterns');
        patternsDiv.innerHTML = '';
        if (data.patterns && data.patterns.length > 0) {
            data.patterns.forEach(p => {
                const chip = document.createElement('div');
                chip.className = 'pattern-block';
                chip.innerHTML = `<i class="fas fa-fingerprint" style="color: #6c757d; margin-right: 8px;"></i> ${p}`;
                patternsDiv.appendChild(chip);
            });
        } else {
            patternsDiv.innerHTML = '<p class="no-data">No patterns identified</p>';
        }

        // Flagged posts with stance
        const flaggedDiv = document.getElementById('agent-flagged');
        flaggedDiv.innerHTML = '';
        if (data.flagged_posts && data.flagged_posts.length > 0) {
            data.flagged_posts.forEach(fp => {
                const stanceCls = {
                    'PROMOTING': 'stance-promoting',
                    'DENOUNCING': 'stance-denouncing',
                    'QUOTING': 'stance-quoting',
                    'SARCASTIC': 'stance-sarcastic',
                    'NEUTRAL': 'stance-neutral'
                }[fp.stance] || 'stance-promoting';
                const cardEl = document.createElement('div');
                cardEl.className = 'flagged-post-card';
                cardEl.innerHTML = `
                    <div class="flagged-header">
                        <span class="stance-badge ${stanceCls}">${fp.stance || 'UNKNOWN'}</span>
                        ${fp.category ? '<span class="category-tag">' + fp.category + '</span>' : ''}
                    </div>
                    <p class="flagged-text">"${fp.text}"</p>
                    <p class="flagged-reason">→ ${fp.reason}</p>
                `;
                flaggedDiv.appendChild(cardEl);
            });
        } else {
            flaggedDiv.innerHTML = '<p class="no-data">No posts flagged by the agent</p>';
        }

        // False positives
        const fpSection = document.getElementById('false-positives-section');
        const fpDiv = document.getElementById('agent-false-positives');
        fpDiv.innerHTML = '';
        if (data.false_positives && data.false_positives.length > 0) {
            fpSection.classList.remove('hidden');
            data.false_positives.forEach(fp => {
                const cardEl = document.createElement('div');
                cardEl.className = 'flagged-post-card false-positive-card';
                cardEl.innerHTML = `
                    <span class="stance-badge stance-denouncing">FALSE POSITIVE</span>
                    <p class="flagged-text">"${fp.text}"</p>
                    <p class="flagged-reason">→ ${fp.reason}</p>
                `;
                fpDiv.appendChild(cardEl);
            });
        } else {
            fpSection.classList.add('hidden');
        }

        // ── Temporal Chart (Chart.js) ──
        const temporalData = data.temporal_data || [];
        const temporalCtx = document.getElementById('temporal-chart');
        
        // Destroy previous chart if any
        if (window._agentTemporalChart) {
            window._agentTemporalChart.destroy();
        }
        
        if (temporalData.length > 0 && temporalCtx) {
            window._agentTemporalChart = new Chart(temporalCtx, {
                type: 'line',
                data: {
                    labels: temporalData.map(d => d.week),
                    datasets: [
                        {
                            label: 'Toxic Rate (%)',
                            data: temporalData.map(d => d.rate),
                            borderColor: '#dc3545',
                            backgroundColor: 'rgba(220,53,69,0.08)',
                            fill: true,
                            tension: 0.3,
                            pointRadius: 4,
                            pointBackgroundColor: '#dc3545',
                            borderWidth: 2
                        },
                        {
                            label: 'Total Posts',
                            data: temporalData.map(d => d.total),
                            borderColor: '#007bff',
                            backgroundColor: 'rgba(0,123,255,0.05)',
                            fill: false,
                            tension: 0.3,
                            pointRadius: 3,
                            pointBackgroundColor: '#007bff',
                            borderWidth: 1.5
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { 
                            position: 'top',
                            labels: { font: { family: 'Inter', size: 11 } }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100,
                            title: { display: true, text: 'Toxic Rate (%)', font: { family: 'Inter', size: 11 } },
                            ticks: { font: { family: 'Inter', size: 10 } }
                        },
                        y1: {
                            position: 'right',
                            beginAtZero: true,
                            title: { display: true, text: 'Total Posts', font: { family: 'Inter', size: 11 } },
                            ticks: { font: { family: 'Inter', size: 10 } },
                            grid: { drawOnChartArea: false } // Only draw grid lines for the first y-axis
                        }
                    }
                }
            });
        }
        // Temporal text analysis
        document.getElementById('agent-temporal').textContent = data.temporal_analysis || 'No temporal data available';

        // ── Network Stat Cards ──
        const netData = data.network_data || {};
        const statsData = data.stats || {};
        
        document.getElementById('net-echo-pct').textContent = (netData.echo_chamber_toxic_pct || 0) + '%';
        document.getElementById('net-reply-ratio').textContent = (netData.reply_ratio_pct || 0) + '%';
        document.getElementById('net-toxic-rate').textContent = (statsData.rate || 0) + '%';
        
        // Color code the values
        const echoPct = netData.echo_chamber_toxic_pct || 0;
        const echoEl = document.getElementById('net-echo-pct');
        echoEl.style.color = echoPct > 50 ? '#dc3545' : echoPct > 20 ? '#f0ad4e' : '#28a745';
        
        const replyPct = netData.reply_ratio_pct || 0;
        const replyEl = document.getElementById('net-reply-ratio');
        replyEl.style.color = replyPct > 60 ? '#dc3545' : replyPct > 30 ? '#f0ad4e' : '#28a745';
        
        const toxicRate = statsData.rate || 0;
        const toxicEl = document.getElementById('net-toxic-rate');
        toxicEl.style.color = toxicRate > 50 ? '#dc3545' : toxicRate > 20 ? '#f0ad4e' : '#28a745';
        
        // ── Top Contacts ──
        const contacts = netData.top_contacts || [];
        const contactsDiv = document.getElementById('top-contacts-container');
        const contactsSection = document.getElementById('top-contacts-section');
        contactsDiv.innerHTML = '';
        
        if (contacts.length > 0) {
            contactsSection.classList.remove('hidden');
            const maxRate = Math.max(1, ...contacts.map(c => c.rate));
            contacts.forEach(c => {
                const barColor = c.rate > 50 ? '#dc3545' : c.rate > 20 ? '#f0ad4e' : '#28a745';
                const row = document.createElement('div');
                row.className = 'contact-row';
                row.innerHTML = `
                    <span class="contact-handle">@${c.handle}</span>
                    <div class="contact-bar-wrapper">
                        <div class="contact-bar-fill" style="width:${(c.rate/maxRate)*100}%; background:${barColor}"></div>
                    </div>
                    <span class="contact-rate" style="color:${barColor}">${c.rate}%</span>
                `;
                contactsDiv.appendChild(row);
            });
        } else {
            contactsSection.classList.add('hidden');
        }

        // Network text analysis
        document.getElementById('agent-network').textContent = data.interactions_analysis || 'No network data available';

        agentResults.classList.remove('hidden');

        // ── Activate inner tabs ──
        const agentTabBtns = document.querySelectorAll('.agent-tab-btn');
        const agentTabContents = document.querySelectorAll('.agent-tab-content');

        // Default to first tab
        agentTabBtns.forEach(b => b.classList.remove('active'));
        agentTabContents.forEach(c => c.classList.remove('active'));
        if (agentTabBtns[0]) agentTabBtns[0].classList.add('active');
        if (agentTabContents[0]) agentTabContents[0].classList.add('active');

        // Tab click handlers
        agentTabBtns.forEach(btn => {
            btn.onclick = () => {
                agentTabBtns.forEach(b => b.classList.remove('active'));
                agentTabContents.forEach(c => c.classList.remove('active'));
                btn.classList.add('active');
                const target = document.getElementById(btn.dataset.agentTab);
                if (target) target.classList.add('active');
            };
        });
    };

    // --- Drilldown Handling ---
    const drilldownContainer = document.getElementById('time-drilldown-container');
    const drilldownTitleStr = document.getElementById('drilldown-time-label');
    const drilldownBody = document.getElementById('drilldown-body');

    const fetchDrilldownData = async (timeLabel) => {
        try {
            drilldownContainer.classList.remove('hidden');
            drilldownTitleStr.textContent = timeLabel + ' (Loading...)';
            drilldownBody.innerHTML = '<tr><td colspan="4" style="text-align:center;">Loading...</td></tr>';
            
            const res = await fetch(`/api/monitoring/posts-by-time?time_label=${encodeURIComponent(timeLabel)}&mode=${currentTimeMode}`);
            const data = await res.json();
            
            drilldownTitleStr.textContent = timeLabel;
            drilldownBody.innerHTML = '';
            
            if (!data.posts || data.posts.length === 0) {
                drilldownBody.innerHTML = '<tr><td colspan="4" style="text-align:center;">No flagged posts found for this period.</td></tr>';
                return;
            }
            
            data.posts.forEach(post => {
                const tr = document.createElement('tr');
                const scorePercent = (post.misogyny_score * 100).toFixed(0);
                const scoreClass = scorePercent > 80 ? 'badge-high' : (scorePercent > 50 ? 'badge-moderate' : 'badge-low');
                tr.innerHTML = `
                    <td class="clickable h-link" data-handle="${post.author_handle}">@${post.author_handle}</td>
                    <td class="text-cell">${post.text}</td>
                    <td><span class="badge ${scoreClass}">${scorePercent}%</span></td>
                    <td>
                        <div style="display: flex; flex-direction: column; gap: 6px; align-items: flex-end;">
                            <button class="view-btn invest-btn" data-handle="${post.author_handle}" style="width: 100%; text-align: center;">INVESTIGATE</button>
                            <button class="view-btn drilldown-deep" data-handle="${post.author_handle}" style="background: #6f42c1; width: 100%; text-align: center;">DEEP ANALYSIS</button>
                        </div>
                    </td>
                `;
                drilldownBody.appendChild(tr);
            });
            
            // Wire up INVESTIGATE buttons → open user modal (same as User Risk)
            drilldownBody.querySelectorAll('.drilldown-investigate, .h-link').forEach(el => {
                el.addEventListener('click', () => showUserDetails(el.getAttribute('data-handle')));
            });
            
            // Wire up DEEP ANALYSIS buttons → switch to Agent Analysis tab & prefill handle
            drilldownBody.querySelectorAll('.drilldown-deep').forEach(el => {
                el.addEventListener('click', () => {
                    const handle = el.getAttribute('data-handle');
                    // Switch to Agent Analysis tab
                    document.querySelectorAll('.tab-button').forEach(b => b.classList.remove('active'));
                    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                    const agentTabBtn = document.querySelector('[data-tab="tab-agent"]');
                    if (agentTabBtn) agentTabBtn.classList.add('active');
                    document.getElementById('tab-agent').classList.add('active');
                    // Pre-fill the handle input
                    const agentInput = document.getElementById('agent-handle');
                    if (agentInput) agentInput.value = handle;
                    // Scroll to top
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                });
            });
            
            drilldownContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            
        } catch (error) {
            console.error('Error fetching drilldown data:', error);
            drilldownBody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:red;">Error loading posts.</td></tr>';
        }
    };
});
