// Main Application JavaScript for Guarita Plate Reader System
class PlateReaderApp {
    constructor() {
        this.currentPage = 1;
        this.currentSearch = '';
        this.currentDateFrom = '';
        this.currentDateTo = '';
        this.deduplicate = false;
        this.timeWindow = 5;
        this.charts = {};
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.updateCurrentTime();
        this.loadDashboard();
        
        // Auto-refresh every 30 seconds
        setInterval(() => {
            if (document.getElementById('dashboard-section').style.display !== 'none') {
                this.refreshDashboard();
            }
        }, 30000);
    }

    setupEventListeners() {
        // Navigation
        document.querySelectorAll('[data-section]').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                this.showSection(e.target.dataset.section);
            });
        });

        // Search functionality
        document.getElementById('search-plate')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.searchPlates();
            }
        });

        // Date inputs
        document.getElementById('date-from')?.addEventListener('change', () => {
            this.searchPlates();
        });

        document.getElementById('date-to')?.addEventListener('change', () => {
            this.searchPlates();
        });

        // Deduplication controls
        document.getElementById('deduplicate-toggle')?.addEventListener('change', (e) => {
            this.deduplicate = e.target.checked;
            const timeWindowControl = document.getElementById('time-window-control');
            if (timeWindowControl) {
                timeWindowControl.style.display = e.target.checked ? 'block' : 'none';
            }
            this.searchPlates();
        });

        document.getElementById('time-window')?.addEventListener('change', (e) => {
            this.timeWindow = parseInt(e.target.value);
            if (this.deduplicate) {
                this.searchPlates();
            }
        });
    }

    updateCurrentTime() {
        const updateTime = () => {
            const now = new Date();
            const timeString = now.toLocaleString('pt-BR', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
            const timeElement = document.getElementById('current-time');
            if (timeElement) {
                timeElement.textContent = timeString;
            }
        };
        
        updateTime();
        setInterval(updateTime, 1000);
    }

    showSection(sectionName) {
        // Hide all sections
        document.querySelectorAll('.content-section').forEach(section => {
            section.style.display = 'none';
        });

        // Remove active class from all nav links
        document.querySelectorAll('.nav-link').forEach(link => {
            link.classList.remove('active');
        });

        // Show selected section
        document.getElementById(`${sectionName}-section`).style.display = 'block';
        document.querySelector(`[data-section="${sectionName}"]`).classList.add('active');

        // Load section-specific data
        switch(sectionName) {
            case 'dashboard':
                this.loadDashboard();
                break;
            case 'placas':
                this.loadPlates();
                break;
            case 'analytics':
                this.loadAnalytics();
                break;
        }
    }

    async loadDashboard() {
        try {
            await Promise.all([
                this.loadOverviewStats(),
                this.loadDailyChart(),
                this.loadHourlyChart(),
                this.loadTopPlates()
            ]);
        } catch (error) {
            this.showToast('Erro ao carregar dashboard: ' + error.message, 'error');
        }
    }

    async refreshDashboard() {
        // Refresh only the stats, keep charts unless specifically requested
        await this.loadOverviewStats();
        await this.loadTopPlates();
    }

    async loadOverviewStats() {
        try {
            const response = await fetch('/api/stats/overview');
            const data = await response.json();

            if (response.ok) {
                document.getElementById('total-reads').textContent = 
                    data.total_reads.toLocaleString('pt-BR');
                document.getElementById('today-reads').textContent = 
                    data.today_reads.toLocaleString('pt-BR');
                document.getElementById('unique-plates').textContent = 
                    data.unique_plates.toLocaleString('pt-BR');
                document.getElementById('avg-confidence').textContent = 
                    (data.avg_confidence * 100).toFixed(1) + '%';
            } else {
                throw new Error(data.error);
            }
        } catch (error) {
            this.showToast('Erro ao carregar estatísticas: ' + error.message, 'error');
        }
    }

    async loadDailyChart(days = 30) {
        try {
            const response = await fetch(`/api/stats/daily?days=${days}`);
            const data = await response.json();

            if (response.ok) {
                const ctx = document.getElementById('dailyChart').getContext('2d');
                
                if (this.charts.daily) {
                    this.charts.daily.destroy();
                }

                this.charts.daily = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: data.map(item => new Date(item.date).toLocaleDateString('pt-BR')),
                        datasets: [{
                            label: 'Leituras',
                            data: data.map(item => item.count),
                            borderColor: 'rgb(13, 110, 253)',
                            backgroundColor: 'rgba(13, 110, 253, 0.1)',
                            borderWidth: 3,
                            fill: true,
                            tension: 0.4,
                            pointBackgroundColor: 'rgb(13, 110, 253)',
                            pointBorderColor: '#fff',
                            pointBorderWidth: 2,
                            pointRadius: 5
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                display: false
                            }
                        },
                        scales: {
                            y: {
                                beginAtZero: true,
                                grid: {
                                    color: 'rgba(0, 0, 0, 0.05)'
                                }
                            },
                            x: {
                                grid: {
                                    display: false
                                }
                            }
                        }
                    }
                });
            } else {
                throw new Error(data.error);
            }
        } catch (error) {
            this.showToast('Erro ao carregar gráfico diário: ' + error.message, 'error');
        }
    }

    async loadHourlyChart() {
        try {
            const today = new Date().toISOString().split('T')[0];
            const response = await fetch(`/api/stats/hourly?date=${today}`);
            const data = await response.json();

            if (response.ok) {
                const ctx = document.getElementById('hourlyChart').getContext('2d');
                
                if (this.charts.hourly) {
                    this.charts.hourly.destroy();
                }

                // Fill missing hours with 0
                const hourlyData = new Array(24).fill(0);
                data.forEach(item => {
                    hourlyData[item.hour] = item.count;
                });

                this.charts.hourly = new Chart(ctx, {
                    type: 'doughnut',
                    data: {
                        labels: hourlyData.map((_, index) => `${index}:00`),
                        datasets: [{
                            data: hourlyData,
                            backgroundColor: [
                                '#ff6384', '#36a2eb', '#cc65fe', '#ffce56',
                                '#4bc0c0', '#9966ff', '#ff9f40', '#ff6384',
                                '#c9cbcf', '#4bc0c0', '#ff6384', '#36a2eb',
                                '#cc65fe', '#ffce56', '#4bc0c0', '#9966ff',
                                '#ff9f40', '#ff6384', '#c9cbcf', '#4bc0c0',
                                '#ff6384', '#36a2eb', '#cc65fe', '#ffce56'
                            ]
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                display: false
                            }
                        }
                    }
                });
            } else {
                throw new Error(data.error);
            }
        } catch (error) {
            this.showToast('Erro ao carregar gráfico horário: ' + error.message, 'error');
        }
    }

    async loadTopPlates() {
        try {
            const response = await fetch('/api/stats/top-plates?limit=10&days=7');
            const data = await response.json();

            if (response.ok) {
                const tbody = document.getElementById('top-plates-body');
                tbody.innerHTML = '';

                data.forEach(plate => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td><strong>${plate.license_number}</strong></td>
                        <td><span class="badge bg-primary">${plate.count}</span></td>
                        <td>${this.getConfidenceBadge(plate.avg_confidence)}</td>
                        <td><small>${new Date(plate.last_seen).toLocaleString('pt-BR')}</small></td>
                    `;
                    tbody.appendChild(row);
                });
            } else {
                throw new Error(data.error);
            }
        } catch (error) {
            this.showToast('Erro ao carregar top placas: ' + error.message, 'error');
        }
    }

    async loadPlates(page = 1) {
        this.currentPage = page;
        const loading = document.getElementById('loading-placas');
        const tbody = document.getElementById('placas-table-body');
        const statusElement = document.getElementById('deduplication-status');
        
        loading.style.display = 'block';
        tbody.innerHTML = '';

        try {
            const params = new URLSearchParams({
                page: page,
                per_page: 50
            });

            if (this.currentSearch) {
                params.append('search', this.currentSearch);
            }
            if (this.currentDateFrom) {
                params.append('date_from', this.currentDateFrom);
            }
            if (this.currentDateTo) {
                params.append('date_to', this.currentDateTo);
            }
            if (this.deduplicate) {
                params.append('deduplicate', 'true');
                params.append('time_window', this.timeWindow);
            }

            const response = await fetch(`/api/placas?${params}`);
            const data = await response.json();

            if (response.ok) {
                // Update status indicator
                if (statusElement) {
                    if (data.deduplicated) {
                        let statusContent = `
                            <div class="alert alert-info mb-3">
                                <i class="fas fa-filter me-2"></i>
                                <strong>Deduplicação ativa:</strong> Agrupando todas as placas em janelas de ${data.time_window} segundos 
                                e mostrando apenas a leitura com maior confiança por janela. 
                                ${data.total} registros únicos encontrados.
                        `;
                        
                        if (data.original_count && data.reduction_percentage) {
                            statusContent += `
                                <br><small class="text-muted">
                                    Redução de ${data.original_count} para ${data.total} registros 
                                    (${data.reduction_percentage}% menos duplicatas)
                                </small>
                            `;
                        }
                        
                        statusContent += '</div>';
                        statusElement.innerHTML = statusContent;
                    } else {
                        statusElement.innerHTML = '';
                    }
                }

                data.data.forEach(placa => {
                    const row = document.createElement('tr');
                    
                    // Construir info adicional para placas deduplicadas
                    let plateInfo = `<strong>${placa.license_number}</strong>`;
                    if (data.deduplicated && placa.group_size && placa.group_size > 1) {
                        // Mostrar informações do grupo de forma mais limpa
                        const uniquePlates = [...new Set(placa.grouped_plates)]; // Remove duplicatas
                        plateInfo += `<br><small class="badge bg-secondary mb-1">
                            ${placa.group_size} leituras em ${placa.group_time_span || 0}s
                        </small>`;
                        
                        if (uniquePlates.length > 1) {
                            plateInfo += `<br><small class="text-muted">
                                <i class="fas fa-layer-group" title="Variações encontradas"></i>
                                Variações: ${uniquePlates.filter(p => p !== placa.license_number).join(', ')}
                            </small>`;
                        }
                    }
                    
                    row.innerHTML = `
                        <td>${placa.id}</td>
                        <td>${placa.frame_nmr}</td>
                        <td>${placa.car_id}</td>
                        <td>${plateInfo}</td>
                        <td>${this.getConfidenceBadge(placa.license_number_score)}</td>
                        <td><small>${new Date(placa.data_hora).toLocaleString('pt-BR')}</small></td>
                        <td>
                            <button class="btn btn-outline-primary btn-sm" 
                                    onclick="app.showPlateDetails(${placa.id})">
                                <i class="fas fa-eye"></i>
                            </button>
                        </td>
                    `;
                    row.classList.add('fade-in');
                    tbody.appendChild(row);
                });

                this.updatePagination(data);
            } else {
                throw new Error(data.error);
            }
        } catch (error) {
            this.showToast('Erro ao carregar placas: ' + error.message, 'error');
        } finally {
            loading.style.display = 'none';
        }
    }

    updatePagination(data) {
        const pagination = document.getElementById('pagination');
        pagination.innerHTML = '';

        const totalPages = data.total_pages;
        const currentPage = data.page;

        // Previous button
        if (currentPage > 1) {
            pagination.innerHTML += `
                <li class="page-item">
                    <a class="page-link" href="#" onclick="app.loadPlates(${currentPage - 1})">
                        <i class="fas fa-chevron-left"></i>
                    </a>
                </li>
            `;
        }

        // Page numbers
        const startPage = Math.max(1, currentPage - 2);
        const endPage = Math.min(totalPages, currentPage + 2);

        if (startPage > 1) {
            pagination.innerHTML += `<li class="page-item"><a class="page-link" href="#" onclick="app.loadPlates(1)">1</a></li>`;
            if (startPage > 2) {
                pagination.innerHTML += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
            }
        }

        for (let i = startPage; i <= endPage; i++) {
            pagination.innerHTML += `
                <li class="page-item ${i === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" onclick="app.loadPlates(${i})">${i}</a>
                </li>
            `;
        }

        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                pagination.innerHTML += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
            }
            pagination.innerHTML += `<li class="page-item"><a class="page-link" href="#" onclick="app.loadPlates(${totalPages})">${totalPages}</a></li>`;
        }

        // Next button
        if (currentPage < totalPages) {
            pagination.innerHTML += `
                <li class="page-item">
                    <a class="page-link" href="#" onclick="app.loadPlates(${currentPage + 1})">
                        <i class="fas fa-chevron-right"></i>
                    </a>
                </li>
            `;
        }
    }

    searchPlates() {
        this.currentSearch = document.getElementById('search-plate').value;
        this.currentDateFrom = document.getElementById('date-from').value;
        this.currentDateTo = document.getElementById('date-to').value;
        this.loadPlates(1);
    }

    getConfidenceBadge(confidence) {
        const percent = (confidence * 100).toFixed(1);
        let badgeClass = 'bg-success';
        
        if (confidence < 0.5) {
            badgeClass = 'bg-danger';
        } else if (confidence < 0.8) {
            badgeClass = 'bg-warning text-dark';
        }
        
        return `<span class="badge ${badgeClass}">${percent}%</span>`;
    }

    showPlateDetails(id) {
        // This could open a modal with more details about the plate reading
        this.showToast(`Detalhes da placa ID: ${id}`, 'info');
    }

    loadAnalytics() {
        // Placeholder for analytics functionality
        this.showToast('Seção de análises em desenvolvimento', 'info');
    }

    showToast(message, type = 'info') {
        const toastElement = document.getElementById('liveToast');
        const toastMessage = document.getElementById('toast-message');
        
        toastMessage.textContent = message;
        
        // Update toast style based on type
        toastElement.className = `toast ${type === 'error' ? 'bg-danger text-white' : type === 'success' ? 'bg-success text-white' : ''}`;
        
        const toast = new bootstrap.Toast(toastElement);
        toast.show();
    }

    // Method to update daily chart with different periods
    updateDailyChart(days) {
        this.loadDailyChart(days);
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    window.app = new PlateReaderApp();
});

// Global functions for onclick handlers
function updateDailyChart(days) {
    window.app.updateDailyChart(days);
}
