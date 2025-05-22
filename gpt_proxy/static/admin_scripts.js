const API_BASE_URL = ''; // 后端 API 的基础路径
        const JWT_TOKEN_LOCALSTORAGE_KEY = 'adminAuthToken';
        // let PROXY_API_KEY = ''; // No longer needed globally, token will be stored
        const REFRESH_INTERVAL_MS = 30000; // 30 秒
        let statsRefreshIntervalId;

        // 分页状态
        let validKeysPageSize = 10;
        let validKeysCurrentPage = 1;
        let validKeysTotalPages = 1;
        let validKeysTotalCount = 0;
        
        let invalidKeysPageSize = 10;
        let invalidKeysCurrentPage = 1;
        let invalidKeysTotalPages = 1;
        let invalidKeysTotalCount = 0;

        // 用于存储当前列表，已不需要存储所有数据
        let validKeysData = [];
        let invalidKeysData = [];

        document.getElementById('refreshInterval').textContent = REFRESH_INTERVAL_MS / 1000;

        async function apiRequest(endpoint, method = 'GET', body = null, isLogin = false) {
            const token = localStorage.getItem(JWT_TOKEN_LOCALSTORAGE_KEY);
            const headers = {};

            if (isLogin) { // For login request, content type is different
                headers['Content-Type'] = 'application/x-www-form-urlencoded';
            } else {
                headers['Content-Type'] = 'application/json';
                if (token) {
                    headers['Authorization'] = `Bearer ${token}`;
                } else if (endpoint !== '/token') { // Don't logout if trying to get token
                    // If no token and not a login attempt, treat as unauthorized for other endpoints
                    console.warn("No token found for API request to protected endpoint:", endpoint);
                    logoutAndShowLogin("会话已过期或未登录，请重新登录。");
                    return null; // Prevent further execution
                }
            }
            
            const fetchConfig = {
                method: method,
                headers: headers
            };

            if (body) {
                if (isLogin) {
                    fetchConfig.body = body; // FormData or URLSearchParams for login
                } else {
                    fetchConfig.body = JSON.stringify(body); // JSON for other requests
                }
            }

            try {
                const response = await fetch(`${API_BASE_URL}${endpoint}`, fetchConfig);
                if (response.status === 401 && !isLogin) { // Unauthorized for non-login requests
                    console.warn("Received 401, logging out. Endpoint:", endpoint);
                    logoutAndShowLogin('认证失败或会话已过期，请重新登录。');
                    return null;
                }
                // For login, 401 is handled by the caller to show specific error
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({ message: `请求失败，状态码: ${response.status}` }));
                    throw new Error(errorData.detail || errorData.message || `HTTP error! status: ${response.status}`);
                }
                if (response.status === 204) { // No Content
                    return true;
                }
                return await response.json();
            } catch (error) {
                console.error('API Request Error:', error);
                // If it's a network error or non-JSON response for a protected endpoint, and no token, it might also mean logout.
                if (!token && endpoint !== '/token' && !isLogin) {
                     logoutAndShowLogin("请求时发生错误，可能需要重新登录。");
                }
                throw error;
            }
        }

        function logoutAndShowLogin(errorMessage = "您已登出。") {
            localStorage.removeItem(JWT_TOKEN_LOCALSTORAGE_KEY);
            if (statsRefreshIntervalId) clearInterval(statsRefreshIntervalId);
            
            document.getElementById('adminContent').classList.add('hidden');
            document.getElementById('authSection').classList.remove('hidden');
            document.getElementById('loading').classList.add('hidden');
            document.getElementById('proxyApiKeyInput').value = ''; // Clear password field
            document.getElementById('topRightActions').classList.add('hidden'); // 隐藏顶部登出按钮
            
            if (errorMessage) {
                showAuthError(errorMessage);
            }
        }

        function showAuthError(message) {
            const authErrorEl = document.getElementById('authError');
            authErrorEl.textContent = message;
            authErrorEl.classList.remove('hidden');
        }

        function showKeyManagementError(message) {
            const keyManagementErrorEl = document.getElementById('keyManagementError');
            keyManagementErrorEl.textContent = message;
            keyManagementErrorEl.classList.remove('hidden');
            setTimeout(() => keyManagementErrorEl.classList.add('hidden'), 5000);
        }

        function showStatsError(message) {
            const statsErrorEl = document.getElementById('statsError');
            statsErrorEl.textContent = message;
            statsErrorEl.classList.remove('hidden');
            setTimeout(() => statsErrorEl.classList.add('hidden'), 5000);
        }

        async function handleLogin() {
            const apiKeyInput = document.getElementById('proxyApiKeyInput');
            const password = apiKeyInput.value.trim();
            if (!password) {
                showAuthError('请输入代理 API Key 作为密码。');
                return;
            }

            document.getElementById('authError').classList.add('hidden');
            document.getElementById('loading').classList.remove('hidden');
            document.getElementById('authSection').classList.add('hidden');
            
            const formData = new URLSearchParams();
            formData.append('username', 'admin'); // Username can be fixed or empty if backend ignores it
            formData.append('password', password);

            try {
                // 登录接口保持在根路径，不使用/api前缀
                const tokenData = await fetch('/token', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded'
                    },
                    body: formData
                }).then(response => {
                    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                    return response.json();
                });
                
                if (tokenData && tokenData.access_token) {
                    localStorage.setItem(JWT_TOKEN_LOCALSTORAGE_KEY, tokenData.access_token);
                    await loadInitialData(); // Load data now that we have a token
                } else {
                    showAuthError('登录失败，未获取到令牌。');
                    logoutAndShowLogin("登录失败，请重试。"); // Ensure UI is reset
                }
            } catch (error) {
                showAuthError(`登录请求失败: ${error.message}`);
                logoutAndShowLogin(`登录请求失败: ${error.message}`); // Ensure UI is reset
            } finally {
                document.getElementById('loading').classList.add('hidden');
            }
        }

        async function loadInitialData() {
            const token = localStorage.getItem(JWT_TOKEN_LOCALSTORAGE_KEY);
            if (!token) {
                logoutAndShowLogin("请先登录。");
                return;
            }

            // Show loading, hide auth section (in case it was visible)
            document.getElementById('loading').classList.remove('hidden');
            document.getElementById('authSection').classList.add('hidden');
            document.getElementById('adminContent').classList.add('hidden'); // Hide content until data loads
            document.getElementById('topRightActions').classList.remove('hidden'); // 显示顶部登出按钮

            try {
                // 尝试加载初始数据
                await loadStats(); // 加载统计信息，包含Key池摘要更新
                await loadValidKeys(1, validKeysPageSize);
                await loadInvalidKeys(1, invalidKeysPageSize);
                
                document.getElementById('adminContent').classList.remove('hidden');
                
                // 设置自动刷新
                if (statsRefreshIntervalId) clearInterval(statsRefreshIntervalId);
                statsRefreshIntervalId = setInterval(loadStats, REFRESH_INTERVAL_MS);
                
                // 初始化分页下拉框
                document.getElementById('validKeysPageSize').value = validKeysPageSize;
                document.getElementById('invalidKeysPageSize').value = invalidKeysPageSize;
            } catch (error) {
                console.error("Error loading initial data:", error);
                logoutAndShowLogin(`加载初始数据失败: ${error.message}`);
            } finally {
                document.getElementById('loading').classList.add('hidden');
            }
        }
        
        // Initial page load logic
        document.addEventListener('DOMContentLoaded', () => {
            loadInitialData();

            const batchResetButton = document.getElementById('batchResetKeysButton');
            if (batchResetButton) {
                batchResetButton.addEventListener('click', batchResetAllKeys);
            }
        });

        async function batchResetAllKeys() {
            if (!confirm('确定要重置所有Key吗？')) {
                return;
            }
            document.getElementById('loading').classList.remove('hidden');
            try {
                const response = await apiRequest('/api/keys/reset_all_keys', 'POST');
                if (response) {
                    alert(response.message || `操作完成，重置了 ${response.count} 个Key。`);
                    // 刷新统计信息和列表
                    await loadStats();
                    await loadValidKeys(1, validKeysPageSize);
                    await loadInvalidKeys(1, invalidKeysPageSize);
                }
            } catch (error) {
                showKeyManagementError(`批量重置Key失败: ${error.message}`);
            } finally {
                document.getElementById('loading').classList.add('hidden');
            }
        }

        function logout() {
            logoutAndShowLogin();
        }

        function maskApiKey(key, forceShow = false) {
            const apiKeySpan = document.createElement('span');
            apiKeySpan.className = 'api-key-display';
            
            if (!key || key.length < 8) {
                apiKeySpan.textContent = key || 'N/A';
                return apiKeySpan;
            }

            const maskedPart = key.substring(0, 3) + '...' + key.substring(key.length - 4);
            let isMasked = true;
            apiKeySpan.textContent = maskedPart;
            apiKeySpan.title = '点击显示/隐藏完整 Key';
            apiKeySpan.style.cursor = 'pointer';

            apiKeySpan.addEventListener('click', (event) => {
                event.stopPropagation(); // Prevent row click or other parent handlers
                isMasked = !isMasked;
                apiKeySpan.textContent = isMasked ? maskedPart : key;
            });

            if (forceShow) {
                apiKeySpan.textContent = key;
                isMasked = false;
            }
            return apiKeySpan;
        }

        function formatDateTime(dateTimeString) {
            if (!dateTimeString) return 'N/A';
            try {
                const date = new Date(dateTimeString);
                // Check if date is valid
                if (isNaN(date.getTime())) {
                    return 'Invalid Date';
                }
                return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
            } catch (e) {
                return 'Invalid Date';
            }
        }

        function renderTable(keysData, tableId, keyType) {
            const tbody = document.getElementById(tableId).getElementsByTagName('tbody')[0];
            tbody.innerHTML = ''; // Clear existing rows
            
            if (keysData.length === 0) {
                const row = tbody.insertRow();
                const cell = row.insertCell();
                cell.colSpan = 6; // Masked Key, Status, Total Calls, Last Used, Created At, Actions
                cell.textContent = `暂无${keyType} Key。`;
                return;
            }
            
            keysData.forEach(key => {
                const row = tbody.insertRow();
                row.insertCell().textContent = key.api_key_masked || 'N/A';
                
                const statusCell = row.insertCell();
                // 将状态文本改为中文
                let statusText = '未知';
                if (key.status === 'active') {
                    statusText = '有效';
                } else if (key.status === 'inactive') {
                    statusText = '无效';
                } else if (key.status === 'revoked') {
                    statusText = '已吊销';
                }
                statusCell.textContent = statusText;
                statusCell.className = key.status === 'active' ? 'status-active' : (key.status === 'inactive' ? 'status-inactive' : 'status-revoked');
                
                row.insertCell().textContent = key.total_requests !== undefined ? key.total_requests : 'N/A';
                row.insertCell().textContent = formatDateTime(key.last_used_at);
                row.insertCell().textContent = formatDateTime(key.created_at);

                const actionsCell = row.insertCell();
                actionsCell.className = 'actions';
                
                const toggleStatusButton = document.createElement('button');
                let newStatus, buttonText;
                if (key.status === 'active') {
                    newStatus = 'inactive';
                    buttonText = '设为无效';
                } else if (key.status === 'inactive') {
                    newStatus = 'active';
                    buttonText = '设为有效';
                } else { // e.g. 'revoked'
                    newStatus = 'active'; // Or 'inactive', depending on desired behavior for revoked keys
                    buttonText = '设为有效'; 
                }
                toggleStatusButton.textContent = buttonText;
                toggleStatusButton.onclick = () => toggleKeyStatus(key.id, newStatus);
                actionsCell.appendChild(toggleStatusButton);

                const deleteButton = document.createElement('button');
                deleteButton.textContent = '删除';
                deleteButton.classList.add('delete-btn');
                deleteButton.onclick = () => deleteOpenAiKey(key.id, key.api_key_masked);
                actionsCell.appendChild(deleteButton);
            });
        }

        function renderPaginationControls(paginationId, currentPage, totalPages, pageSize, totalCount, loadFunction) {
            const paginationContainer = document.getElementById(paginationId);
            paginationContainer.innerHTML = '';

            if (totalPages <= 1) {
                return;
            }

            // 首页按钮
            const firstButton = document.createElement('button');
            firstButton.textContent = '首页';
            firstButton.disabled = currentPage === 1;
            firstButton.onclick = () => loadFunction(1, pageSize);
            paginationContainer.appendChild(firstButton);

            // 上一页按钮
            const prevButton = document.createElement('button');
            prevButton.textContent = '上一页';
            prevButton.disabled = currentPage === 1;
            prevButton.onclick = () => loadFunction(currentPage - 1, pageSize);
            paginationContainer.appendChild(prevButton);

            // 页码信息
            const pageInfo = document.createElement('span');
            pageInfo.className = 'page-info';
            pageInfo.textContent = `第 ${currentPage} / ${totalPages} 页 (共 ${totalCount} 条)`;
            paginationContainer.appendChild(pageInfo);

            // 下一页按钮
            const nextButton = document.createElement('button');
            nextButton.textContent = '下一页';
            nextButton.disabled = currentPage === totalPages;
            nextButton.onclick = () => loadFunction(currentPage + 1, pageSize);
            paginationContainer.appendChild(nextButton);

            // 末页按钮
            const lastButton = document.createElement('button');
            lastButton.textContent = '末页';
            lastButton.disabled = currentPage === totalPages;
            lastButton.onclick = () => loadFunction(totalPages, pageSize);
            paginationContainer.appendChild(lastButton);
        }
        
        async function promptEditKeyName(keyId, currentName) {
            const newName = prompt(`请输入 Key ID ${keyId} 的新名称:`, currentName);
            if (newName !== null && newName.trim() !== '') {
                try {
                    const result = await apiRequest(`/api/keys/${keyId}/name`, 'PUT', { name: newName.trim() });
                    if (result) {
                        // 刷新统计信息和列表
                        await loadStats();
                        await loadValidKeys(validKeysCurrentPage, validKeysPageSize);
                        await loadInvalidKeys(invalidKeysCurrentPage, invalidKeysPageSize);
                    }
                } catch (error) {
                    showKeyManagementError(`更新 Key 名称失败: ${error.message}`);
                }
            } else if (newName === '') {
                showKeyManagementError('Key 名称不能为空。');
            }
        }

        // 加载Key池统计信息
        async function loadStats() {
            try {
                const response = await apiRequest('/api/stats'); // Expects { global_stats: { ... } }
                if (!response || !response.global_stats) {
                    showStatsError('加载统计数据失败：返回数据格式不正确。');
                    // Clear dashboard values
                    document.getElementById('callsLast1m').textContent = 'N/A';
                    document.getElementById('callsLast1h').textContent = 'N/A';
                    document.getElementById('callsLast24h').textContent = 'N/A';
                    document.getElementById('callsTotal').textContent = 'N/A';
                    // Clear key stats
                    document.getElementById('activeKeysCount').textContent = 'N/A';
                    document.getElementById('inactiveKeysCount').textContent = 'N/A';
                    document.getElementById('revokedKeysCount').textContent = 'N/A';
                    document.getElementById('totalKeysCount').textContent = 'N/A';
                    return;
                }

                const globalStats = response.global_stats;

                // Populate new dashboard cards
                document.getElementById('callsLast1m').textContent = globalStats.grand_total_usage_last_1m;
                document.getElementById('callsLast1h').textContent = globalStats.grand_total_usage_last_1h;
                document.getElementById('callsLast24h').textContent = globalStats.grand_total_usage_last_24h;
                document.getElementById('callsTotal').textContent = globalStats.grand_total_requests_all_time;

                // Populate key stats (which are still in globalStats)
                document.getElementById('activeKeysCount').textContent = globalStats.active_keys_count;
                document.getElementById('inactiveKeysCount').textContent = globalStats.inactive_keys_count;
                document.getElementById('revokedKeysCount').textContent = globalStats.revoked_keys_count;
                document.getElementById('totalKeysCount').textContent = globalStats.total_keys_count;
                
                // 更新 Key 池摘要信息
                const totalValidKeys = globalStats.active_keys_count;
                const totalInvalidKeys = globalStats.inactive_keys_count + globalStats.revoked_keys_count;
                const totalKeys = globalStats.total_keys_count;
                
                const keyStatsEl = document.getElementById('keyStats');
                keyStatsEl.innerHTML = `总 Key 数量: <strong>${totalKeys}</strong> (有效: <strong class="status-active">${totalValidKeys}</strong>, 无效: <strong class="status-inactive">${totalInvalidKeys}</strong>)`;
                document.getElementById('keyManagementError').classList.add('hidden');
                
                document.getElementById('statsError').classList.add('hidden');
            } catch (error) {
                showStatsError(`加载统计数据失败: ${error.message}`);
                if (statsRefreshIntervalId) clearInterval(statsRefreshIntervalId);
                // Clear dashboard values on error
                document.getElementById('callsLast1m').textContent = '错误';
                document.getElementById('callsLast1h').textContent = '错误';
                document.getElementById('callsLast24h').textContent = '错误';
                document.getElementById('callsTotal').textContent = '错误';
                // Clear key stats on error
                document.getElementById('activeKeysCount').textContent = '错误';
                document.getElementById('inactiveKeysCount').textContent = '错误';
                document.getElementById('revokedKeysCount').textContent = '错误';
                document.getElementById('totalKeysCount').textContent = '错误';
                
                // 显示 Key 池摘要错误
                const keyStatsEl = document.getElementById('keyStats');
                keyStatsEl.innerHTML = `<span class="error-message">无法加载 Key 统计信息。</span>`;
            }
        }

        // 加载有效的Keys（使用分页API）
        async function loadValidKeys(page, pageSize) {
            try {
                const endpoint = `/api/keys/paginated?page=${page}&page_size=${pageSize}&status=active`;
                const response = await apiRequest(endpoint);
                
                if (!response || !response.items || !response.page_info) {
                    showKeyManagementError('加载有效Key失败：返回数据格式不正确。');
                    validKeysData = [];
                    renderTable(validKeysData, 'validKeysTable', 'valid');
                    return;
                }
                
                validKeysData = response.items;
                validKeysCurrentPage = response.page_info.page;
                validKeysTotalPages = response.page_info.total_pages;
                validKeysTotalCount = response.page_info.total;
                validKeysPageSize = response.page_info.page_size;
                
                renderTable(validKeysData, 'validKeysTable', 'valid');
                renderPaginationControls(
                    'validKeysPagination', 
                    validKeysCurrentPage, 
                    validKeysTotalPages, 
                    validKeysPageSize, 
                    validKeysTotalCount, 
                    loadValidKeys
                );
            } catch (error) {
                showKeyManagementError(`加载有效Key失败: ${error.message}`);
                validKeysData = [];
                renderTable(validKeysData, 'validKeysTable', 'valid');
            }
        }

        // 加载无效的Keys（使用分页API）
        async function loadInvalidKeys(page, pageSize) {
            try {
                // 无效Key包括inactive和revoked状态，需要多次请求后合并
                // 先获取inactive状态的keys
                const inactiveEndpoint = `/api/keys/paginated?page=${page}&page_size=${pageSize}&status=inactive`;
                const inactiveResponse = await apiRequest(inactiveEndpoint);
                
                // 可选：获取revoked状态的keys
                // const revokedEndpoint = `/api/keys/paginated?page=${page}&page_size=${pageSize}&status=revoked`;
                // const revokedResponse = await apiRequest(revokedEndpoint);
                
                if (!inactiveResponse || !inactiveResponse.items || !inactiveResponse.page_info) {
                    showKeyManagementError('加载无效Key失败：返回数据格式不正确。');
                    invalidKeysData = [];
                    renderTable(invalidKeysData, 'invalidKeysTable', 'invalid');
                    return;
                }
                
                invalidKeysData = inactiveResponse.items;
                invalidKeysCurrentPage = inactiveResponse.page_info.page;
                invalidKeysTotalPages = inactiveResponse.page_info.total_pages;
                invalidKeysTotalCount = inactiveResponse.page_info.total;
                invalidKeysPageSize = inactiveResponse.page_info.page_size;
                
                renderTable(invalidKeysData, 'invalidKeysTable', 'invalid');
                renderPaginationControls(
                    'invalidKeysPagination', 
                    invalidKeysCurrentPage, 
                    invalidKeysTotalPages, 
                    invalidKeysPageSize, 
                    invalidKeysTotalCount, 
                    loadInvalidKeys
                );
            } catch (error) {
                showKeyManagementError(`加载无效Key失败: ${error.message}`);
                invalidKeysData = [];
                renderTable(invalidKeysData, 'invalidKeysTable', 'invalid');
            }
        }

        // 更改有效Keys每页显示数量
        function changeValidKeysPageSize(newSize) {
            validKeysPageSize = parseInt(newSize);
            loadValidKeys(1, validKeysPageSize);
        }

        // 更改无效Keys每页显示数量
        function changeInvalidKeysPageSize(newSize) {
            invalidKeysPageSize = parseInt(newSize);
            loadInvalidKeys(1, invalidKeysPageSize);
        }

        async function addOpenAiKeys() {
            const newKeysInput = document.getElementById('newOpenAiKeys');
            const keysString = newKeysInput.value.trim();
            if (!keysString) {
                showKeyManagementError('请输入 OpenAI API Key。');
                return;
            }

            const keysArray = keysString.split(/\r?\n/).map(k => k.trim()).filter(k => k);
            if (keysArray.length === 0) {
                showKeyManagementError('未检测到有效的 API Key。请确保每行一个 Key。');
                return;
            }

            let allValidFormat = true;
            for (const key of keysArray) {
                if (!key.startsWith('sk-')) {
                    allValidFormat = false;
                    break;
                }
            }
            if (!allValidFormat) {
                showKeyManagementError('一个或多个 OpenAI API Key 格式不正确，应以 "sk-" 开头。');
                return;
            }
            
            document.getElementById('loading').classList.remove('hidden');
            
            try {
                // 使用批量添加API
                const result = await apiRequest('/api/keys/bulk', 'POST', { api_keys: keysString });
                document.getElementById('loading').classList.add('hidden');
                newKeysInput.value = ''; // Clear textarea
                
                // 刷新统计信息和列表
                await loadStats();
                await loadValidKeys(1, validKeysPageSize);
                await loadInvalidKeys(1, invalidKeysPageSize);

                if (result.error_count > 0) {
                    const errorDetails = result.results
                        .filter(r => !r.success)
                        .map(r => `Key ${r.key_suffix} 添加失败: ${r.error_message}`)
                        .join('\n');
                    
                    showKeyManagementError(`批量添加完成: ${result.success_count} 个成功, ${result.error_count} 个失败。\n失败详情:\n${errorDetails}`);
                } else {
                    alert(`成功添加 ${result.success_count} 个 Key。`);
                }
            } catch (error) {
                document.getElementById('loading').classList.add('hidden');
                showKeyManagementError(`批量添加Key失败: ${error.message}`);
            }
        }

        async function deleteOpenAiKey(keyId, displayKey) {
            if (!confirm(`确定要删除 Key "${displayKey}" 吗？`)) {
                return;
            }
            try {
                const result = await apiRequest(`/api/keys/${keyId}`, 'DELETE');
                if (result) {
                    // 刷新统计信息和列表
                    await loadStats();
                    await loadValidKeys(validKeysCurrentPage, validKeysPageSize);
                    await loadInvalidKeys(invalidKeysCurrentPage, invalidKeysPageSize);
                }
            } catch (error) {
                showKeyManagementError(`删除 Key 失败: ${error.message}`);
            }
        }

        async function toggleKeyStatus(keyId, newStatus) {
            try {
                const newStatusText = newStatus === 'active' ? '有效' : (newStatus === 'inactive' ? '无效' : '已吊销');
                if (confirm(`确定要将此Key状态更改为 ${newStatusText} 吗？`)) {
                    const result = await apiRequest(`/api/keys/${keyId}/status`, 'PUT', { status: newStatus });
                    if (result) {
                        // 刷新统计信息和列表
                        await loadStats();
                        await loadValidKeys(validKeysCurrentPage, validKeysPageSize);
                        await loadInvalidKeys(invalidKeysCurrentPage, invalidKeysPageSize);
                    }
                }
            } catch (error) {
                showKeyManagementError(`更新Key状态失败: ${error.message}`);
            }
        }

        async function triggerValidateKeys() {
            if (!confirm('确定要重新验证所有失效的 Key 吗？这可能需要一些时间。')) {
                return;
            }
            document.getElementById('loading').classList.remove('hidden');
            try {
                const result = await apiRequest('/api/validate_keys', 'POST');
                if (result) {
                    alert('Key 验证请求已发送。请稍后刷新查看最新状态。');
                    // 刷新统计信息和列表
                    await loadStats();
                    await loadValidKeys(1, validKeysPageSize);
                    await loadInvalidKeys(1, invalidKeysPageSize);
                }
            } catch (error) {
                showKeyManagementError(`触发 Key 验证失败: ${error.message}`);
            } finally {
                document.getElementById('loading').classList.add('hidden');
            }
        }