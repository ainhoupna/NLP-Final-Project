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
        answerText.innerHTML = '<em>Analizando...</em>';
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
                answerText.innerText = "Error 501: El servicio RAG no está implementado todavía.";
            } else {
                const data = await response.json();
                answerText.innerText = data.answer || "No se ha podido procesar la respuesta.";
                
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
            answerText.innerText = "Error: No se pudo conectar con el servidor.";
        } finally {
            questionInput.disabled = false;
        }
    });

    // --- Stats Handling ---
    const fetchStats = async () => {
        try {
            const response = await fetch('/stats');
            if (response.status === 501) {
                statCount.innerText = "N/A";
                statLlm.innerText = "No implementado";
            } else {
                const data = await response.json();
                statCount.innerText = data.indexed_posts || 0;
                statLlm.innerText = data.llm_status || "Desconocido";
                statLastSync.innerText = data.last_scrape || "Nunca";
                
                statLlm.classList.remove('gray');
                statLastSync.classList.remove('gray');
            }
        } catch (error) {
            console.error('Error fetching stats:', error);
        }
    };

    refreshStatsBtn.addEventListener('click', fetchStats);

    // Initial load
    fetchStats();
});
