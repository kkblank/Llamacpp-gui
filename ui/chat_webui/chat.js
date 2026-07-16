/* ===== State ===== */
const state = {
  llamaUrl: '',
  conversations: [],
  currentConvId: null,
  messages: [],
  conversationAgents: [],
  agents: [],
  streaming: true,
  isSending: false,
  abortController: null,
  reasoningDisplay: 'collapsed',
  pendingImages: [],
  connOk: false,
  mentionOpen: false,
  mentionFilter: '',
  mentionIdx: 0,
};

/* ===== Init ===== */
async function init() {
  const saved = loadLocalSettings();
  if (saved.llamaUrl) state.llamaUrl = saved.llamaUrl;
  if (saved.reasoningDisplay) state.reasoningDisplay = saved.reasoningDisplay;

  document.getElementById('setting-api-url').value = state.llamaUrl;
  document.getElementById('setting-reasoning-display').value = state.reasoningDisplay;

  await loadAgents();
  await loadConversations();
  bindEvents();
  updateConnStatus();

  if (state.llamaUrl) {
    try { await checkConnection(); } catch {}
  }
}

/* ===== Local Settings ===== */
function loadLocalSettings() {
  try { return JSON.parse(localStorage.getItem('chat_settings') || '{}'); } catch { return {}; }
}
function saveLocalSettings() {
  localStorage.setItem('chat_settings', JSON.stringify({
    llamaUrl: state.llamaUrl,
    reasoningDisplay: state.reasoningDisplay,
  }));
}

/* ===== Connection ===== */
async function checkConnection() {
  const url = state.llamaUrl.replace(/\/+$/, '');
  const el = document.getElementById('conn-test-result');
  try {
    const res = await fetch(url + '/v1/models', { method: 'GET', signal: AbortSignal.timeout(5000) });
    state.connOk = res.ok;
  } catch {
    try {
      const res = await fetch(url + '/health', { method: 'GET', signal: AbortSignal.timeout(5000) });
      state.connOk = res.ok;
    } catch {
      state.connOk = false;
    }
  }
  updateConnStatus();
  if (el) {
    el.textContent = state.connOk ? '✅ 连接成功' : '❌ 连接失败';
    el.style.color = state.connOk ? '#4f8cff' : '#e74c5c';
  }
}

function updateConnStatus() {
  const el = document.getElementById('conn-status');
  const text = document.getElementById('conn-url-text');
  if (state.connOk && state.llamaUrl) {
    el.className = 'conn-status connected';
    text.textContent = state.llamaUrl.replace(/^https?:\/\//, '');
  } else if (state.llamaUrl) {
    el.className = 'conn-status disconnected';
    text.textContent = '连接失败';
  } else {
    el.className = 'conn-status disconnected';
    text.textContent = '未配置';
  }
}

function openApiSetup() {
  document.getElementById('setting-api-url').value = state.llamaUrl;
  document.getElementById('conn-test-result').textContent = '';
  openModal('settings-modal');
}

/* ===== Bridge API (relative) ===== */
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch('/' + path.replace(/^\/+/, ''), opts);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const j = await res.json(); msg = j.error || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

/* ===== Agents (global) ===== */
async function loadAgents() {
  try {
    const data = await api('GET', 'agents');
    state.agents = data.agents || [];
  } catch {
    state.agents = [];
  }
  if (!state.agents.some(a => a.id === 'default')) {
    state.agents.unshift({ id: 'default', name: '默认助手', system_prompt: '你是一个有用的AI助手。', temperature: 0.8, alias: '' });
  }
  renderAgentChips();
  renderAgentList();
}

async function saveAgent(id, data) {
  if (id && !id.startsWith('new-')) {
    await api('PUT', `agents/${id}`, data);
  } else {
    await api('POST', 'agents', data);
  }
  await loadAgents();
}

async function deleteAgent(id) {
  if (id === 'default') return;
  await api('DELETE', `agents/${id}`);
  state.conversationAgents = state.conversationAgents.filter(aid => aid !== id);
  await loadAgents();
}

/* ===== Conversations ===== */
async function loadConversations() {
  try {
    const data = await api('GET', 'conversations');
    state.conversations = data.conversations || [];
  } catch {
    state.conversations = [];
  }
  renderConversations();
}

async function selectConversation(id) {
  if (state.isSending) return;
  state.currentConvId = id;
  state.messages = [];
  state.conversationAgents = [];
  try {
    const conv = await api('GET', `conversations/${id}`);
    state.messages = conv.messages || [];
    state.conversationAgents = conv.agents || [];
  } catch {}
  enableInput(state.conversationAgents.length > 0);
  renderMessages();
  renderConversations();
  renderAgentChips();
  scrollToBottom();
}

async function newConversation() {
  if (state.isSending) return;
  try {
    const conv = await api('POST', 'conversations', { title: '新对话', agents: [], messages: [] });
    state.currentConvId = conv.id;
    state.messages = [];
    state.conversationAgents = [];
    enableInput(false);
    await loadConversations();
    renderMessages();
    renderAgentChips();
    selectConversation(conv.id);
  } catch {}
}

async function deleteConversation(id) {
  if (state.isSending) return;
  try {
    await api('DELETE', `conversations/${id}`);
    if (state.currentConvId === id) {
      state.currentConvId = null;
      state.messages = [];
      state.conversationAgents = [];
      enableInput(false);
      renderMessages();
    }
    renderAgentChips();
    await loadConversations();
  } catch {}
}

async function renameConversation(id) {
  const conv = state.conversations.find(c => c.id === id);
  if (!conv) return;
  const title = prompt('对话名称：', conv.title);
  if (!title || title === conv.title) return;
  try {
    await api('PUT', `conversations/${id}`, { title });
    await loadConversations();
  } catch {}
}

async function saveConversation(id, messages) {
  await api('PUT', `conversations/${id}`, { messages, agents: state.conversationAgents });
}

async function saveConversationAgents(id) {
  await api('PUT', `conversations/${id}`, { agents: state.conversationAgents });
}

/* ===== LLM API - @mention + Parallel ===== */
function parseMentions(text) {
  const names = text.match(/@([^\s@]+)/g) || [];
  return names.map(n => n.slice(1)).filter(Boolean);
}

async function sendMessage() {
  if (state.isSending) return;
  if (!state.connOk) { openApiSetup(); return; }

  const input = document.getElementById('input-box');
  const text = input.value.trim();
  const images = state.pendingImages;
  if (!text && images.length === 0) return;

  const mentionedNames = parseMentions(text);
  let targetAgents;
  if (mentionedNames.length > 0) {
    targetAgents = state.agents.filter(a =>
      state.conversationAgents.includes(a.id) && mentionedNames.includes(a.name)
    );
  } else {
    targetAgents = state.agents.filter(a => state.conversationAgents.includes(a.id));
    if (targetAgents.length > 0) targetAgents = [targetAgents[0]];
  }
  if (targetAgents.length === 0) return;

  if (!state.currentConvId) {
    try {
      const conv = await api('POST', 'conversations', { title: text.slice(0, 20) || '新对话', agents: [], messages: [] });
      state.currentConvId = conv.id;
      await loadConversations();
    } catch { return; }
  }

  const userMsg = buildUserMessage(text, images);
  state.messages.push(userMsg);
  input.value = '';
  clearImages();
  state.isSending = true;
  renderMessages(true);
  scrollToBottom();
  showStopButton(true);

  const streaming = state.streaming;
  const baseUrl = state.llamaUrl.replace(/\/+$/, '');

  const promises = targetAgents.map(async (agent) => {
    const messages = buildMessagesForAgent(agent);
    const assistantMsg = { role: 'assistant', content: '', reasoning_content: '', agent_id: agent.id, agent_name: agent.name };

    if (streaming) {
      const msgIdx = state.messages.length;
      state.messages.push(assistantMsg);
      // render after push — don't render per agent, batch
      renderMessages(true);
      scrollToBottom();

      try {
        await streamChat(baseUrl, messages, agent, (delta) => {
          if (delta.reasoning_content) state.messages[msgIdx].reasoning_content += delta.reasoning_content;
          if (delta.content) state.messages[msgIdx].content += delta.content;
          renderMessages(true);
          scrollToBottom();
        });
      } catch (err) {
        if (err.name === 'AbortError') {
          state.messages[msgIdx].content += '\n[已停止]';
        } else {
          state.messages[msgIdx].content = `[错误] ${err.message}`;
        }
        renderMessages(true);
        scrollToBottom();
      }
    } else {
      state.messages.push(assistantMsg);
      renderMessages(true);

      try {
        const result = await nonStreamChat(baseUrl, messages, agent);
        const last = state.messages[state.messages.length - 1];
        last.content = result.content || '';
        last.reasoning_content = result.reasoning_content || '';
        renderMessages(true);
        scrollToBottom();
      } catch (err) {
        state.messages[state.messages.length - 1].content = `[错误] ${err.message}`;
        renderMessages(true);
        scrollToBottom();
      }
    }
  });

  await Promise.all(promises);

  state.isSending = false;
  showStopButton(false);
  await saveConversation(state.currentConvId, state.messages);
}

function buildUserMessage(text, images) {
  if (images.length === 0) return { role: 'user', content: text };
  const parts = [];
  if (text) parts.push({ type: 'text', text });
  for (const img of images) parts.push({ type: 'image_url', image_url: { url: img.dataUrl } });
  return { role: 'user', content: parts };
}

function buildMessagesForAgent(agent) {
  const result = [];
  if (agent.system_prompt) result.push({ role: 'system', content: agent.system_prompt });
  for (const msg of state.messages) {
    if (msg.role === 'system') continue;
    let content = msg.content;
    if (msg.role === 'assistant' && msg.agent_name && msg.agent_name !== agent.name) {
      content = `[${msg.agent_name}]: ${content}`;
    }
    result.push({ role: msg.role, content });
  }
  return result;
}

async function streamChat(baseUrl, messages, agent, onDelta) {
  state.abortController = new AbortController();
  const body = { messages, stream: true, temperature: agent.temperature != null ? agent.temperature : 0.8 };

  const res = await fetch(baseUrl + '/v1/chat/completions', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body), signal: state.abortController.signal,
  });

  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const j = await res.json(); msg = j.error?.message || msg; } catch {}
    throw new Error(msg);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      const t = line.trim();
      if (!t || t === 'data: [DONE]' || !t.startsWith('data: ')) continue;
      try {
        const json = JSON.parse(t.slice(6));
        const choice = json.choices && json.choices[0];
        if (!choice) continue;
        const delta = choice.delta || {};
        onDelta({ content: delta.content || '', reasoning_content: delta.reasoning_content || '' });
        if (choice.finish_reason === 'length') onDelta({ content: '\n[达到长度限制]' });
      } catch {}
    }
  }
  state.abortController = null;
}

async function nonStreamChat(baseUrl, messages, agent) {
  const body = { messages, stream: false, temperature: agent.temperature != null ? agent.temperature : 0.8 };
  const res = await fetch(baseUrl + '/v1/chat/completions', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const j = await res.json(); msg = j.error?.message || msg; } catch {}
    throw new Error(msg);
  }
  const json = await res.json();
  const choice = json.choices && json.choices[0];
  if (!choice) throw new Error('no response');
  const msg = choice.message || {};
  return { content: msg.content || '', reasoning_content: msg.reasoning_content || '' };
}

function stopGeneration() {
  if (state.abortController) { state.abortController.abort(); state.abortController = null; }
}

/* ===== Edit Message ===== */
function editMessages(index) {
  if (state.isSending) return;
  const msg = state.messages[index];
  if (!msg || msg.role !== 'user') return;
  const content = typeof msg.content === 'string' ? msg.content : '[图片消息]';
  const newText = prompt('编辑消息（截断到此处）：', content);
  if (newText === null) return;
  state.messages = state.messages.slice(0, index + 1);
  state.messages[index].content = newText;
  renderMessages();
  saveConversation(state.currentConvId, state.messages);
}

/* ===== @mention ===== */
function openMentionPopover() {
  const popover = document.getElementById('mention-popover');
  const participants = getParticipants();
  state.mentionOpen = true;
  state.mentionFilter = '';
  state.mentionIdx = 0;
  renderMentionList(participants);
  popover.hidden = false;
}

function closeMentionPopover() {
  state.mentionOpen = false;
  document.getElementById('mention-popover').hidden = true;
}

function renderMentionList(filtered) {
  const list = document.getElementById('mention-list');
  list.innerHTML = '';
  if (filtered.length === 0) {
    list.innerHTML = '<div class="mention-item" style="color:var(--text-muted)">无匹配成员</div>';
    return;
  }
  for (let i = 0; i < filtered.length; i++) {
    const item = document.createElement('div');
    item.className = 'mention-item' + (i === state.mentionIdx ? ' selected' : '');
    item.textContent = '@' + filtered[i].name;
    item.dataset.name = filtered[i].name;
    item.addEventListener('mousedown', (e) => { e.preventDefault(); });
    item.addEventListener('click', () => {
      insertMention(filtered[i].name);
    });
    item.addEventListener('mousemove', () => { state.mentionIdx = i; renderMentionList(filtered); });
    list.appendChild(item);
  }
}

function filterMention(text) {
  const input = document.getElementById('input-box');
  const cursor = input.selectionStart;
  const before = input.value.slice(0, cursor);
  const atIdx = before.lastIndexOf('@');
  if (atIdx === -1) { closeMentionPopover(); return; }
  state.mentionFilter = before.slice(atIdx + 1);

  const participants = getParticipants();
  const filtered = participants.filter(a => a.name.includes(state.mentionFilter));
  state.mentionIdx = 0;
  if (filtered.length === 0) { closeMentionPopover(); return; }
  renderMentionList(filtered);
  document.getElementById('mention-popover').hidden = false;
  state.mentionOpen = true;
}

function insertMention(name) {
  const input = document.getElementById('input-box');
  const cursor = input.selectionStart;
  const before = input.value.slice(0, cursor);
  const atIdx = before.lastIndexOf('@');
  const after = input.value.slice(cursor);
  input.value = before.slice(0, atIdx) + '@' + name + ' ' + after;
  const newPos = atIdx + name.length + 2;
  input.setSelectionRange(newPos, newPos);
  input.focus();
  closeMentionPopover();
}

function getParticipants() {
  return state.agents.filter(a => state.conversationAgents.includes(a.id));
}

/* ===== Add/Remove Members ===== */
function openAddMemberModal() {
  const list = document.getElementById('member-select-list');
  list.innerHTML = '';
  state.mentionSelected = [];

  const alreadyInConv = state.conversationAgents;
  const available = state.agents.filter(a => !alreadyInConv.includes(a.id));

  if (available.length === 0) {
    list.innerHTML = '<div style="color:var(--text-muted);padding:8px 0">所有角色已在群聊中</div>';
    document.getElementById('btn-add-members-done').disabled = true;
  } else {
    document.getElementById('btn-add-members-done').disabled = false;
    for (const a of available) {
      const div = document.createElement('div');
      div.className = 'member-check-item';
      div.innerHTML = `<input type="checkbox" id="member-${a.id}" data-id="${a.id}"><label for="member-${a.id}">${escapeHtml(a.name)}</label>`;
      list.appendChild(div);
    }
  }
  openModal('add-member-modal');
}

function confirmAddMembers() {
  const checkboxes = document.querySelectorAll('#member-select-list input[type="checkbox"]:checked');
  const newIds = Array.from(checkboxes).map(cb => cb.dataset.id);
  if (newIds.length === 0) { closeModal('add-member-modal'); return; }

  state.conversationAgents.push(...newIds);
  closeModal('add-member-modal');
  renderAgentChips();
  enableInput(true);
  if (state.currentConvId) saveConversationAgents(state.currentConvId);
}

function removeParticipant(id) {
  state.conversationAgents = state.conversationAgents.filter(aid => aid !== id);
  renderAgentChips();
  if (state.conversationAgents.length === 0) enableInput(false);
  if (state.currentConvId) saveConversationAgents(state.currentConvId);
}

/* ===== Image Handling ===== */
function handleImageUpload(files) {
  for (const file of files) {
    if (!file.type.startsWith('image/')) continue;
    const reader = new FileReader();
    reader.onload = (e) => {
      state.pendingImages.push({ file, dataUrl: e.target.result, name: file.name });
      renderImagePreviews();
    };
    reader.readAsDataURL(file);
  }
}

function removeImage(idx) { state.pendingImages.splice(idx, 1); renderImagePreviews(); }
function clearImages() { state.pendingImages = []; renderImagePreviews(); }

/* ===== Rendering ===== */
function renderConversations() {
  const list = document.getElementById('conv-list'); list.innerHTML = '';
  for (const conv of state.conversations) {
    const div = document.createElement('div');
    div.className = 'conv-item' + (conv.id === state.currentConvId ? ' active' : '');
    div.dataset.id = conv.id;
    const title = document.createElement('span'); title.className = 'conv-title'; title.textContent = conv.title || '未命名对话';
    div.appendChild(title);
    const del = document.createElement('button'); del.className = 'conv-del'; del.textContent = '×';
    del.title = '删除对话';
    del.addEventListener('click', (e) => { e.stopPropagation(); deleteConversation(conv.id); });
    div.appendChild(del);
    div.addEventListener('click', () => selectConversation(conv.id));
    div.addEventListener('dblclick', () => renameConversation(conv.id));
    list.appendChild(div);
  }
}

function renderAgentChips() {
  const chips = document.getElementById('agent-chips'); chips.innerHTML = '';
  const participants = getParticipants();
  for (const agent of participants) {
    const chip = document.createElement('span');
    chip.className = 'agent-chip participant';
    chip.textContent = agent.name;
    if (state.conversationAgents.length > 1) {
      const remove = document.createElement('button');
      remove.className = 'chip-remove'; remove.textContent = '×';
      remove.addEventListener('click', (e) => { e.stopPropagation(); removeParticipant(agent.id); });
      chip.appendChild(remove);
    }
    chips.appendChild(chip);
  }
}

function renderMessages(scroll) {
  const area = document.getElementById('message-area'); area.innerHTML = '';
  if (state.messages.length === 0) {
    area.innerHTML = '<div class="empty-hint">@ 助手开始对话</div>';
    return;
  }
  for (let i = 0; i < state.messages.length; i++) {
    const msg = state.messages[i];
    const group = document.createElement('div'); group.className = 'msg-group';
    if (msg.role === 'user') {
      const bubble = document.createElement('div');
      bubble.className = 'msg user' + (i === state.messages.length - 1 && state.isSending ? ' streaming' : '');
      bubble.innerHTML = renderContentWithMentions(msg.content);
      bubble.addEventListener('dblclick', () => editMessages(i));
      group.appendChild(bubble);
    } else if (msg.role === 'assistant') {
      const bubble = document.createElement('div');
      const isLast = i === state.messages.length - 1;
      bubble.className = 'msg assistant' + (isLast && state.isSending ? ' streaming' : '');
      if (msg.agent_name) {
        const label = document.createElement('div'); label.className = 'msg-agent-label'; label.textContent = msg.agent_name;
        bubble.appendChild(label);
      }
      if (msg.reasoning_content) {
        const block = document.createElement('div'); block.className = 'think-block';
        if (state.reasoningDisplay === 'hidden') block.style.display = 'none';
        const toggle = document.createElement('div'); toggle.className = 'think-toggle';
        toggle.innerHTML = '<span class="arrow">▶</span> 思考过程';
        toggle.addEventListener('click', () => {
          const cd = toggle.nextElementSibling; const arrow = toggle.querySelector('.arrow');
          arrow.classList.toggle('open', cd.classList.toggle('open'));
        });
        block.appendChild(toggle);
        const cd = document.createElement('div'); cd.className = 'think-content' + (state.reasoningDisplay === 'expanded' ? ' open' : '');
        cd.textContent = msg.reasoning_content; block.appendChild(cd); bubble.appendChild(block);
      }
      const contentDiv = document.createElement('div'); contentDiv.className = 'msg-content';
      contentDiv.innerHTML = renderContent(msg.content); bubble.appendChild(contentDiv);
      group.appendChild(bubble);
    }
    area.appendChild(group);
  }
  if (scroll) scrollToBottom();
}

function renderContentWithMentions(content) {
  if (typeof content !== 'string') return renderContent(content);
  let html = escapeHtml(content);
  html = html.replace(/\n/g, '<br>');
  html = html.replace(/(@[\u4e00-\u9fff\w]+)/g, '<span class="mention">$1</span>');
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => `<div class="msg-code">${escapeHtml(code)}</div>`);
  return html;
}

function renderContent(content) {
  if (typeof content !== 'string') {
    if (Array.isArray(content)) {
      return content.map(part => {
        if (part.type === 'text') return escapeHtml(part.text).replace(/\n/g, '<br>') + '<br>';
        if (part.type === 'image_url') return `<img src="${escapeHtml(part.image_url.url)}" alt="image">`;
        return '';
      }).join('');
    }
    return String(content);
  }
  let html = escapeHtml(content);
  html = html.replace(/\n/g, '<br>');
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => `<div class="msg-code">${escapeHtml(code)}</div>`);
  return html;
}

function escapeHtml(str) { const d = document.createElement('div'); d.textContent = str; return d.innerHTML; }

function renderImagePreviews() {
  const container = document.getElementById('image-previews'); container.innerHTML = '';
  for (let i = 0; i < state.pendingImages.length; i++) {
    const img = state.pendingImages[i];
    const wrapper = document.createElement('div'); wrapper.style.position = 'relative'; wrapper.style.display = 'inline-block';
    const el = document.createElement('img'); el.className = 'img-preview'; el.src = img.dataUrl; el.title = img.name;
    wrapper.appendChild(el);
    const remove = document.createElement('button'); remove.className = 'img-remove'; remove.textContent = '×';
    remove.addEventListener('click', () => removeImage(i)); wrapper.appendChild(remove);
    container.appendChild(wrapper);
  }
}

function renderAgentList() {
  const list = document.getElementById('agent-list'); list.innerHTML = '';
  for (const agent of state.agents) {
    const card = document.createElement('div'); card.className = 'agent-card';
    card.innerHTML = `
      <div class="agent-info"><div class="agent-name">${escapeHtml(agent.name)}</div><div class="agent-prompt">${escapeHtml(agent.system_prompt || '(无 system prompt)')}</div></div>
      <div class="agent-actions"><button class="btn-edit" data-id="${agent.id}">✎</button>${agent.id !== 'default' ? '<button class="btn-del" data-id="' + agent.id + '">×</button>' : ''}</div>`;
    card.querySelector('.btn-edit').addEventListener('click', () => openAgentEditor(agent));
    const delBtn = card.querySelector('.btn-del'); if (delBtn) delBtn.addEventListener('click', () => deleteAgent(agent.id));
    list.appendChild(card);
  }
}

function enableInput(enabled) {
  const input = document.getElementById('input-box');
  const send = document.getElementById('btn-send');
  const area = document.getElementById('input-area');
  input.disabled = !enabled; send.disabled = !enabled;
  area.classList.toggle('disabled', !enabled);
  if (enabled && !input.value) input.placeholder = '输入消息...（@ 助手名称指定回复对象）';
}

function showStopButton(show) { document.getElementById('btn-send').hidden = show; document.getElementById('btn-stop').hidden = !show; }

function scrollToBottom() { const area = document.getElementById('message-area'); area.scrollTop = area.scrollHeight; }

/* ===== Modal ===== */
function openModal(id) { document.getElementById(id).hidden = false; }
function closeModal(id) { document.getElementById(id).hidden = true; }

function openAgentEditor(agent) {
  document.getElementById('agent-edit-title').textContent = agent ? '编辑角色' : '添加角色';
  document.getElementById('agent-edit-name').value = agent ? agent.name : '';
  document.getElementById('agent-edit-prompt').value = agent ? (agent.system_prompt || '') : '';
  document.getElementById('agent-edit-temp').value = agent && agent.temperature != null ? agent.temperature : 0.8;
  document.getElementById('agent-edit-modal').dataset.editingId = agent ? agent.id : '';
  openModal('agent-edit-modal');
}

/* ===== Events ===== */
function bindEvents() {
  document.getElementById('btn-send').addEventListener('click', sendMessage);
  document.getElementById('btn-stop').addEventListener('click', stopGeneration);

  const input = document.getElementById('input-box');
  input.addEventListener('keydown', (e) => {
    if (state.mentionOpen) {
      if (e.key === 'Escape') { closeMentionPopover(); e.preventDefault(); return; }
      if (e.key === 'ArrowDown') {
        state.mentionIdx = Math.min(state.mentionIdx + 1, getParticipants().length - 1);
        renderMentionList(getParticipants().filter(a => a.name.includes(state.mentionFilter)));
        e.preventDefault(); return;
      }
      if (e.key === 'ArrowUp') {
        state.mentionIdx = Math.max(state.mentionIdx - 1, 0);
        renderMentionList(getParticipants().filter(a => a.name.includes(state.mentionFilter)));
        e.preventDefault(); return;
      }
      if (e.key === 'Tab' || e.key === 'Enter') {
        const participants = getParticipants().filter(a => a.name.includes(state.mentionFilter));
        if (participants[state.mentionIdx]) { insertMention(participants[state.mentionIdx].name); e.preventDefault(); return; }
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); return; }
  });
  input.addEventListener('input', (e) => {
    autoResizeInput();
    const cursor = input.selectionStart;
    const before = input.value.slice(0, cursor);
    const atIdx = before.lastIndexOf('@');
    const prevChar = atIdx > 0 ? before[atIdx - 1] : ' ';
    if (atIdx !== -1 && (prevChar === ' ' || prevChar === '\n')) {
      filterMention(e.target.value);
    } else {
      closeMentionPopover();
    }
  });
  input.addEventListener('blur', () => setTimeout(closeMentionPopover, 200));

  // Image upload
  document.getElementById('btn-upload').addEventListener('click', () => document.getElementById('file-input').click());
  document.getElementById('file-input').addEventListener('change', (e) => { handleImageUpload(e.target.files); e.target.value = ''; });

  // Stream toggle
  document.getElementById('stream-toggle').addEventListener('change', (e) => { state.streaming = e.target.checked; });

  // New chat
  document.getElementById('btn-new-chat').addEventListener('click', newConversation);

  // Connection status
  document.getElementById('conn-status').addEventListener('click', openApiSetup);

  // Add/remove members
  document.getElementById('btn-add-member').addEventListener('click', openAddMemberModal);
  document.getElementById('btn-add-members-done').addEventListener('click', confirmAddMembers);

  // Agent management
  document.getElementById('btn-manage-agents').addEventListener('click', () => { renderAgentList(); openModal('agent-modal'); });
  document.getElementById('btn-add-agent').addEventListener('click', () => openAgentEditor(null));
  document.getElementById('btn-agent-save').addEventListener('click', async () => {
    const id = document.getElementById('agent-edit-modal').dataset.editingId;
    const data = {
      name: document.getElementById('agent-edit-name').value.trim() || '未命名角色',
      system_prompt: document.getElementById('agent-edit-prompt').value,
      temperature: parseFloat(document.getElementById('agent-edit-temp').value) || 0.8,
    };
    await saveAgent(id, data);
    closeModal('agent-edit-modal');
  });

  // Settings
  document.getElementById('btn-settings').addEventListener('click', () => {
    document.getElementById('setting-api-url').value = state.llamaUrl;
    document.getElementById('conn-test-result').textContent = '';
    openModal('settings-modal');
  });
  document.getElementById('btn-test-connection').addEventListener('click', async () => {
    const url = document.getElementById('setting-api-url').value.trim();
    if (!url) { document.getElementById('conn-test-result').textContent = '请输入 API 地址'; return; }
    state.llamaUrl = url; await checkConnection();
  });
  document.getElementById('btn-save-settings').addEventListener('click', () => {
    state.llamaUrl = document.getElementById('setting-api-url').value.trim();
    state.reasoningDisplay = document.getElementById('setting-reasoning-display').value;
    saveLocalSettings();
    if (state.llamaUrl) checkConnection();
    closeModal('settings-modal');
  });

  // Modal close
  for (const btn of document.querySelectorAll('.modal-close')) {
    const id = btn.dataset.modal;
    if (id) btn.addEventListener('click', () => closeModal(id));
  }
  for (const modal of document.querySelectorAll('.modal')) {
    modal.addEventListener('click', (e) => { if (e.target.classList.contains('modal-backdrop')) closeModal(modal.id); });
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      for (const modal of document.querySelectorAll('.modal')) { if (!modal.hidden) closeModal(modal.id); }
    }
  });
}

function autoResizeInput() {
  const el = document.getElementById('input-box');
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 150) + 'px';
}

/* ===== Start ===== */
document.addEventListener('DOMContentLoaded', init);
