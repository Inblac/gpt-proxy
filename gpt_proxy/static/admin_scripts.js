const API_BASE_URL = '/admin'; // 后端 API 的基础路径
        const JWT_TOKEN_LOCALSTORAGE_KEY = 'adminAuthToken';
        // let PROXY_API_KEY = ''; // No longer needed globally, token will be stored
        const REFRESH_INTERVAL_MS = 30000; // 30 秒
        let statsRefreshIntervalId;

        // Pagination state for Key Pool
        let validKeysData = [];
        let invalidKeysData = [];
        let currentValidKeyPage = 1;
        let currentInvalidKeyPage = 1;
        const KEYS_PER_PAGE = 10; // Or any other number you prefer

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
                const tokenData = await apiRequest('/token', 'POST', formData, true); // true for isLogin
                if (tokenData && tokenData.access_token) {
                    localStorage.setItem(JWT_TOKEN_LOCALSTORAGE_KEY, tokenData.access_token);
                    await loadInitialData(); // Load data now that we have a token
                } else {
                    // apiRequest might throw, or return null/undefined if it handles the error display
                    // If it returns here without tokenData, it's an issue.
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

            try {
                // Attempt to fetch initial data (e.g., keys) to verify token and load page
                const keys = await apiRequest('/keys'); // This will use the stored token
                if (keys !== null) { // apiRequest returns null on auth failure handled by logoutAndShowLogin
                    document.getElementById('adminContent').classList.remove('hidden');
                    loadKeyPool(); // Assumes this function populates based on `keys` or makes its own call
                    loadStats();   // Assumes this function makes its own call
                    if (statsRefreshIntervalId) clearInterval(statsRefreshIntervalId);
                    statsRefreshIntervalId = setInterval(loadStats, REFRESH_INTERVAL_MS);
                } else {
                    // If keys is null, apiRequest should have called logoutAndShowLogin
                    // No further action needed here as UI should be reset.
                }
            } catch (error) {
                console.error("Error loading initial data:", error);
                // apiRequest might have already called logoutAndShowLogin if it was an auth error.
                // If it's another error, we might want to show a generic error or still logout.
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
                batchResetButton.addEventListener('click', batchResetInvalidKeysToValid);
            }
        });

        async function batchResetInvalidKeysToValid() {
            if (!confirm('确定要将所有无效Key重置为有效状态吗？')) {
                return;
            }
            document.getElementById('loading').classList.remove('hidden');
            try {
                const response = await apiRequest('/keys/reset_invalid_to_valid', 'POST');
                if (response) {
                    alert(response.message || `操作完成，重置了 ${response.count} 个Key。`);
                    loadKeyPool(); // Refresh the key lists
                }
            } catch (error) {
                showKeyManagementError(`批量重置Key失败: ${error.message}`);
            } finally {
                document.getElementById('loading').classList.add('hidden');
            }
        }

        function logout() {
            logoutAndShowLogin("您已成功登出。");
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

        // Generic function to render a table of keys (valid or invalid)
        function renderKeysTable(keysData, tableId, paginationContainerId, currentPage, keysPerPage, keyType) {
            const tbody = document.getElementById(tableId).getElementsByTagName('tbody')[0];
            tbody.innerHTML = ''; // Clear existing rows

            const startIndex = (currentPage - 1) * keysPerPage;
            const endIndex = startIndex + keysPerPage;
            const keysToShow = keysData.slice(startIndex, endIndex);

            if (keysToShow.length === 0 && keysData.length > 0) {
                // This case should be handled by adjusting currentPage before calling this function
                // For safety, if it happens, log it.
                console.warn(`RenderKeysTable called for ${tableId} with empty keysToShow but keysData is not empty. CurrentPage: ${currentPage}`);
                // We might need to adjust currentPage here if it's out of bounds.
                // For now, it will show "暂无 Key" if keysToShow is empty.
            }
            
            if (keysToShow.length === 0) {
                const row = tbody.insertRow();
                const cell = row.insertCell();
                cell.colSpan = 7; // Masked Key, Name, Status, Total Calls, Last Used, Created At, Actions
                cell.textContent = `暂无${keyType} Key。`;
            } else {
                keysToShow.forEach(key => {
                    const row = tbody.insertRow();
                    // row.insertCell().textContent = key.id; // ID 列已移除
                    row.insertCell().textContent = key.api_key_masked || 'N/A';
                    row.insertCell().textContent = key.name || 'N/A';
                    
                    const statusCell = row.insertCell();
                    statusCell.textContent = key.status;
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
                        buttonText = '设为 Inactive';
                    } else if (key.status === 'inactive') {
                        newStatus = 'active';
                        buttonText = '设为 Active';
                    } else { // e.g. 'revoked'
                        newStatus = 'active'; // Or 'inactive', depending on desired behavior for revoked keys
                        buttonText = '尝试设为 Active'; // Or a different text
                    }
                    toggleStatusButton.textContent = buttonText;
                    toggleStatusButton.onclick = () => toggleKeyStatus(key.id, newStatus);
                    actionsCell.appendChild(toggleStatusButton);

                    const editNameButton = document.createElement('button');
                    editNameButton.textContent = '改名';
                    editNameButton.onclick = () => promptEditKeyName(key.id, key.name || '');
                    actionsCell.appendChild(editNameButton);

                    const deleteButton = document.createElement('button');
                    deleteButton.textContent = '删除';
                    deleteButton.classList.add('delete-btn');
                    deleteButton.onclick = () => deleteOpenAiKey(key.id, key.api_key_masked);
                    actionsCell.appendChild(deleteButton);
                });
            }
            renderPaginationControls(keysData.length, currentPage, keysPerPage, paginationContainerId, keyType);
        }

        function renderPaginationControls(totalItems, currentPage, itemsPerPage, containerId, keyType) {
            const paginationContainer = document.getElementById(containerId);
            paginationContainer.innerHTML = '';

            const totalPages = Math.ceil(totalItems / itemsPerPage);

            if (totalPages <= 1) {
                return;
            }

            const prevButton = document.createElement('button');
            prevButton.textContent = '上一页';
            prevButton.disabled = currentPage === 1;
            prevButton.onclick = () => {
                if (currentPage > 1) {
                    if (keyType === 'valid') {
                        currentValidKeyPage--;
                        renderKeysTable(validKeysData, 'validKeysTable', 'validKeysPagination', currentValidKeyPage, KEYS_PER_PAGE, 'valid');
                    } else if (keyType === 'invalid') {
                        currentInvalidKeyPage--;
                        renderKeysTable(invalidKeysData, 'invalidKeysTable', 'invalidKeysPagination', currentInvalidKeyPage, KEYS_PER_PAGE, 'invalid');
                    }
                }
            };
            paginationContainer.appendChild(prevButton);

            const pageInfo = document.createElement('span');
            pageInfo.className = 'page-info';
            pageInfo.textContent = `第 ${currentPage} / ${totalPages} 页`;
            paginationContainer.appendChild(pageInfo);

            const nextButton = document.createElement('button');
            nextButton.textContent = '下一页';
            nextButton.disabled = currentPage === totalPages;
            nextButton.onclick = () => {
                if (currentPage < totalPages) {
                     if (keyType === 'valid') {
                        currentValidKeyPage++;
                        renderKeysTable(validKeysData, 'validKeysTable', 'validKeysPagination', currentValidKeyPage, KEYS_PER_PAGE, 'valid');
                    } else if (keyType === 'invalid') {
                        currentInvalidKeyPage++;
                        renderKeysTable(invalidKeysData, 'invalidKeysTable', 'invalidKeysPagination', currentInvalidKeyPage, KEYS_PER_PAGE, 'invalid');
                    }
                }
            };
            paginationContainer.appendChild(nextButton);
        }
        
        async function promptEditKeyName(keyId, currentName) {
            const newName = prompt(`请输入 Key ID ${keyId} 的新名称:`, currentName);
            if (newName !== null && newName.trim() !== '') {
                try {
                    const result = await apiRequest(`/keys/${keyId}/name`, 'PUT', { name: newName.trim() });
                    if (result) {
                        loadKeyPool(); // Reload all keys to reflect the name change
                    }
                } catch (error) {
                    showKeyManagementError(`更新 Key 名称失败: ${error.message}`);
                }
            } else if (newName === '') {
                showKeyManagementError('Key 名称不能为空。');
            }
        }

        async function loadKeyPool() {
            try {
                const categorizedKeys = await apiRequest('/keys'); // Expects { valid_keys: [], invalid_keys: [] }
                if (!categorizedKeys || typeof categorizedKeys.valid_keys === 'undefined' || typeof categorizedKeys.invalid_keys === 'undefined') {
                    showKeyManagementError('加载 Key 池失败：返回数据格式不正确。');
                    validKeysData = [];
                    invalidKeysData = [];
                } else {
                    validKeysData = categorizedKeys.valid_keys;
                    invalidKeysData = categorizedKeys.invalid_keys;
                }

                const totalKeys = validKeysData.length + invalidKeysData.length;
                const keyStatsEl = document.getElementById('keyStats');
                keyStatsEl.innerHTML = `总 Key 数量: <strong>${totalKeys}</strong> (有效: <strong class="status-active">${validKeysData.length}</strong>, 无效: <strong class="status-inactive">${invalidKeysData.length}</strong>)`;
                
                // Adjust current page if it's out of bounds for valid keys
                let totalValidPages = Math.ceil(validKeysData.length / KEYS_PER_PAGE);
                if (currentValidKeyPage > totalValidPages && totalValidPages > 0) {
                    currentValidKeyPage = totalValidPages;
                } else if (totalValidPages === 0) {
                    currentValidKeyPage = 1;
                }

                // Adjust current page if it's out of bounds for invalid keys
                let totalInvalidPages = Math.ceil(invalidKeysData.length / KEYS_PER_PAGE);
                if (currentInvalidKeyPage > totalInvalidPages && totalInvalidPages > 0) {
                    currentInvalidKeyPage = totalInvalidPages;
                } else if (totalInvalidPages === 0) {
                    currentInvalidKeyPage = 1;
                }

                renderKeysTable(validKeysData, 'validKeysTable', 'validKeysPagination', currentValidKeyPage, KEYS_PER_PAGE, 'valid');
                renderKeysTable(invalidKeysData, 'invalidKeysTable', 'invalidKeysPagination', currentInvalidKeyPage, KEYS_PER_PAGE, 'invalid');
                
                document.getElementById('keyManagementError').classList.add('hidden');
            } catch (error) {
                showKeyManagementError(`加载 Key 池失败: ${error.message}`);
                const keyStatsEl = document.getElementById('keyStats');
                keyStatsEl.innerHTML = `<span class="error-message">无法加载 Key 统计信息。</span>`;
                validKeysData = [];
                invalidKeysData = [];
                renderKeysTable(validKeysData, 'validKeysTable', 'validKeysPagination', 1, KEYS_PER_PAGE, 'valid');
                renderKeysTable(invalidKeysData, 'invalidKeysTable', 'invalidKeysPagination', 1, KEYS_PER_PAGE, 'invalid');
            }
        }

        async function addOpenAiKeys() {
            const newKeysInput = document.getElementById('newOpenAiKeys'); // Changed ID
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
            let successCount = 0;
            let errorCount = 0;
            let errors = [];

            for (const key of keysArray) {
                try {
                    const result = await apiRequest('/keys', 'POST', { api_key: key });
                    if (result) {
                        successCount++;
                    } else { // Should not happen if apiRequest throws on error, but as a safeguard
                        errorCount++;
                        errors.push(`Key ${maskApiKey(key, false).textContent} 添加失败 (未知原因)`);
                    }
                } catch (error) {
                    errorCount++;
                    errors.push(`Key ${maskApiKey(key, false).textContent} 添加失败: ${error.message}`);
                }
            }
            
            document.getElementById('loading').classList.add('hidden');
            newKeysInput.value = ''; // Clear textarea
            loadKeyPool(); // Reload list

            if (errorCount > 0) {
                showKeyManagementError(`批量添加完成: ${successCount} 个成功, ${errorCount} 个失败。\n失败详情:\n${errors.join('\n')}`);
            } else {
                // Optionally show a success message if all were successful
                // For now, loadKeyPool will refresh and show them.
                // You could use a temporary success message similar to error message if desired.
                alert(`成功添加 ${successCount} 个 Key。`);
            }
        }

        async function deleteOpenAiKey(keyId, displayKey) { // Changed maskedKey to displayKey for clarity
            if (!confirm(`确定要删除 Key "${displayKey}" 吗？`)) { // Corrected to use displayKey
                return;
            }
            try {
                const result = await apiRequest(`/keys/${keyId}`, 'DELETE');
                if (result) {
                    loadKeyPool(); // 重新加载列表
                }
            } catch (error) {
                showKeyManagementError(`删除 Key 失败: ${error.message}`);
            }
        }

        async function toggleKeyStatus(keyId, newStatus) {
            try {
                const result = await apiRequest(`/keys/${keyId}/status`, 'PUT', { status: newStatus });
                if (result) {
                    loadKeyPool(); // 重新加载列表
                }
            } catch (error) {
                showKeyManagementError(`更新 Key 状态失败: ${error.message}`);
            }
        }

        async function triggerValidateKeys() {
            if (!confirm('确定要重新验证所有失效的 Key 吗？这可能需要一些时间。')) {
                return;
            }
            document.getElementById('loading').classList.remove('hidden');
            try {
                const result = await apiRequest('/validate_keys', 'POST');
                if (result) {
                    alert('Key 验证请求已发送。请稍后刷新查看最新状态。'); // 或者可以设计成轮询结果
                    loadKeyPool(); // 重新加载 Key 列表以反映可能的状态变化
                }
            } catch (error) {
                showKeyManagementError(`触发 Key 验证失败: ${error.message}`);
            } finally {
                document.getElementById('loading').classList.add('hidden');
            }
        }

        async function loadStats() {
            try {
                const response = await apiRequest('/stats'); // Expects { global_stats: { ... } }
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
            }
        }

        // 初始时不加载数据，等待用户输入代理 API Key
        // window.onload = () => {
        //     // 页面加载时不自动执行，等待用户验证
        // };