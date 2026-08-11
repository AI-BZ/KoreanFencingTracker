/**
 * FencingMind Club - Schedule Calendar
 * FullCalendar v6 Integration
 */

// ─── State ───
let calendar = null;
let coaches = [];
let members = [];
let currentFilter = 'all'; // all, club, coaches, my
let currentEventId = null;

const EVENT_COLORS = {
    training: '#667eea',
    lesson: '#48bb78',
    competition: '#ed8936',
    club_event: '#9f7aea',
    holiday: '#fc8181',
    personal: '#4fd1c5',
    meeting: '#f6ad55',
};

const EVENT_LABELS = {
    training: 'Training',
    lesson: 'Lesson',
    competition: 'Competition',
    club_event: 'Club Event',
    holiday: 'Holiday',
    personal: 'Personal',
    meeting: 'Meeting',
};

const API_BASE = '/api/schedule';
const TEST_SUFFIX = '';

// ─── Initialization ───
document.addEventListener('DOMContentLoaded', () => {
    initCalendar();
    loadCoaches();
    loadMembers();
});

function initCalendar() {
    const calendarEl = document.getElementById('calendar');

    calendar = new FullCalendar.Calendar(calendarEl, {
        // View
        initialView: 'dayGridMonth',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay',
        },
        buttonText: {
            today: 'Today',
            month: 'Month',
            week: 'Week',
            day: 'Day',
        },

        // Locale
        locale: 'ko',
        firstDay: 0, // Sunday

        // Features
        editable: true,
        selectable: true,
        selectMirror: true,
        dayMaxEvents: 4,
        navLinks: true,
        nowIndicator: true,

        // Height
        height: 'auto',
        contentHeight: 'auto',

        // Events Source
        events: fetchEvents,

        // Interactions
        select: handleDateSelect,
        eventClick: handleEventClick,
        eventDrop: handleEventDrop,
        eventResize: handleEventResize,

        // Rendering
        eventDidMount: function(info) {
            // Add tooltip
            info.el.title = info.event.title;

            // Add event type indicator
            const type = info.event.extendedProps.event_type;
            if (type) {
                info.el.dataset.eventType = type;
            }
        },

        // Loading indicator
        loading: function(isLoading) {
            document.body.style.cursor = isLoading ? 'wait' : '';
        },
    });

    calendar.render();
}

// ─── Data Fetching ───
async function fetchEvents(info, successCallback, failureCallback) {
    try {
        const params = new URLSearchParams({
            start: info.startStr,
            end: info.endStr,
        });

        // Apply visibility filter
        if (currentFilter === 'club') {
            params.set('visibility', 'club');
        } else if (currentFilter === 'coaches') {
            params.set('visibility', 'coaches');
        }
        // 'my' and 'all' are handled client-side

        // Coach filter
        const coachId = document.getElementById('coachFilter').value;
        if (coachId) {
            params.set('coach_id', coachId);
        }

        const sep = TEST_SUFFIX ? '&' : '?';
        const url = `${API_BASE}/events${TEST_SUFFIX}${TEST_SUFFIX ? '&' : '?'}${params.toString()}`;

        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to fetch events');

        let events = await response.json();

        // Client-side event type filtering
        const checkedTypes = getCheckedEventTypes();
        events = events.filter(ev => checkedTypes.includes(ev.event_type));

        // Transform for FullCalendar
        const fcEvents = events.map(ev => ({
            id: ev.id,
            title: ev.title,
            start: ev.start,
            end: ev.end,
            allDay: ev.allDay || false,
            color: ev.color || EVENT_COLORS[ev.event_type] || '#667eea',
            extendedProps: {
                event_type: ev.event_type,
                description: ev.description,
                visibility: ev.visibility,
                created_by: ev.created_by,
                creator_name: ev.creator_name,
                assigned_coach_id: ev.assigned_coach_id,
                coach_name: ev.coach_name,
                participant_ids: ev.participant_ids,
                location: ev.location,
                status: ev.status,
                is_recurring: ev.is_recurring,
                recurrence_rule: ev.recurrence_rule,
            },
        }));

        successCallback(fcEvents);
    } catch (err) {
        console.error('Error fetching events:', err);
        failureCallback(err);
    }
}

async function loadCoaches() {
    try {
        const response = await fetch(`${API_BASE}/coaches${TEST_SUFFIX}`);
        if (!response.ok) return;
        const data = await response.json();
        coaches = data.coaches || [];

        // Populate coach filter dropdown
        const coachFilter = document.getElementById('coachFilter');
        const evCoach = document.getElementById('evCoach');

        coaches.forEach(c => {
            const opt1 = new Option(c.name, c.id);
            const opt2 = new Option(c.name, c.id);
            coachFilter.add(opt1);
            evCoach.add(opt2);
        });
    } catch (err) {
        console.warn('Failed to load coaches:', err);
    }
}

async function loadMembers() {
    try {
        const response = await fetch(`${API_BASE}/members${TEST_SUFFIX}`);
        if (!response.ok) return;
        const data = await response.json();
        members = data.members || [];
    } catch (err) {
        console.warn('Failed to load members:', err);
    }
}

// ─── Calendar Interactions ───
function handleDateSelect(info) {
    openCreateModal(info.startStr, info.endStr, info.allDay);
    calendar.unselect();
}

function handleEventClick(info) {
    showEventDetail(info.event);
}

async function handleEventDrop(info) {
    const ev = info.event;
    try {
        const params = new URLSearchParams({
            start: ev.start.toISOString(),
            end: (ev.end || ev.start).toISOString(),
        });
        if (ev.allDay !== undefined) {
            params.set('all_day', ev.allDay);
        }

        const response = await fetch(
            `${API_BASE}/events/${ev.id}/move${TEST_SUFFIX}${TEST_SUFFIX ? '&' : '?'}${params.toString()}`,
            { method: 'PATCH' }
        );
        if (!response.ok) {
            info.revert();
            alert('Failed to move event');
        }
    } catch (err) {
        info.revert();
        console.error('Move failed:', err);
    }
}

async function handleEventResize(info) {
    // Same as drop - update end time
    await handleEventDrop(info);
}

// ─── Filters ───
function setFilter(filter) {
    currentFilter = filter;

    // Update tab UI
    document.querySelectorAll('.filter-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.filter === filter);
    });

    calendar.refetchEvents();
}

function applyFilters() {
    calendar.refetchEvents();
}

function getCheckedEventTypes() {
    const checks = document.querySelectorAll('#eventTypeFilters input[type="checkbox"]');
    return Array.from(checks).filter(c => c.checked).map(c => c.value);
}

function jumpToDate(dateStr) {
    if (dateStr) {
        calendar.gotoDate(dateStr);
    }
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
}

// ─── Create/Edit Modal ───
function openCreateModal(startStr, endStr, allDay) {
    currentEventId = null;
    document.getElementById('modalTitle').textContent = 'New Event';
    document.getElementById('eventId').value = '';
    document.getElementById('btnDelete').style.display = 'none';

    // Reset form
    document.getElementById('eventForm').reset();

    // Set defaults
    if (startStr) {
        const start = allDay ? startStr + 'T09:00' : startStr.slice(0, 16);
        document.getElementById('evStart').value = start;

        if (endStr) {
            const end = allDay ? endStr + 'T10:00' : endStr.slice(0, 16);
            document.getElementById('evEnd').value = end;
        } else {
            // Default 1 hour
            const d = new Date(startStr);
            d.setHours(d.getHours() + 1);
            document.getElementById('evEnd').value = d.toISOString().slice(0, 16);
        }
    } else {
        // Default now + 1 hour
        const now = new Date();
        now.setMinutes(0, 0, 0);
        const end = new Date(now);
        end.setHours(end.getHours() + 1);
        document.getElementById('evStart').value = formatLocalDatetime(now);
        document.getElementById('evEnd').value = formatLocalDatetime(end);
    }

    if (allDay) {
        document.getElementById('evAllDay').checked = true;
    }

    updateColorPreview();
    document.getElementById('eventModal').style.display = 'flex';
}

function openEditModal(eventData) {
    currentEventId = eventData.id;
    document.getElementById('modalTitle').textContent = 'Edit Event';
    document.getElementById('eventId').value = eventData.id;
    document.getElementById('btnDelete').style.display = 'inline-flex';

    // Fill form
    document.getElementById('evTitle').value = eventData.title || '';
    document.getElementById('evType').value = eventData.event_type || 'training';
    document.getElementById('evStart').value = (eventData.start || '').slice(0, 16);
    document.getElementById('evEnd').value = (eventData.end || '').slice(0, 16);
    document.getElementById('evAllDay').checked = eventData.allDay || false;
    document.getElementById('evVisibility').value = eventData.visibility || 'club';
    document.getElementById('evCoach').value = eventData.assigned_coach_id || '';
    document.getElementById('evColor').value = eventData.color || EVENT_COLORS[eventData.event_type] || '#667eea';
    document.getElementById('evLocation').value = eventData.location || '';
    document.getElementById('evDescription').value = eventData.description || '';

    // Recurrence
    const isRec = eventData.is_recurring || false;
    document.getElementById('evRecurring').checked = isRec;
    document.getElementById('recurrenceOptions').style.display = isRec ? 'block' : 'none';
    if (isRec && eventData.recurrence_rule) {
        document.getElementById('evRecFreq').value = eventData.recurrence_rule.freq || 'weekly';
        document.getElementById('evRecUntil').value = eventData.recurrence_rule.until || '';
        if (eventData.recurrence_rule.days) {
            document.querySelectorAll('#dayPickerGroup input[type="checkbox"]').forEach(cb => {
                cb.checked = eventData.recurrence_rule.days.includes(parseInt(cb.value));
            });
        }
    }

    updateColorPreview();
    document.getElementById('eventModal').style.display = 'flex';
}

function closeModal() {
    document.getElementById('eventModal').style.display = 'none';
    currentEventId = null;
}

// ─── Save Event ───
async function saveEvent(e) {
    e.preventDefault();

    const isEdit = !!currentEventId;
    const data = {
        title: document.getElementById('evTitle').value,
        event_type: document.getElementById('evType').value,
        start_at: new Date(document.getElementById('evStart').value).toISOString(),
        end_at: new Date(document.getElementById('evEnd').value).toISOString(),
        all_day: document.getElementById('evAllDay').checked,
        visibility: document.getElementById('evVisibility').value,
        assigned_coach_id: document.getElementById('evCoach').value || null,
        color: document.getElementById('evColor').value,
        location: document.getElementById('evLocation').value || null,
        description: document.getElementById('evDescription').value || null,
    };

    // Recurrence
    if (document.getElementById('evRecurring').checked && !isEdit) {
        data.is_recurring = true;
        const days = [];
        document.querySelectorAll('#dayPickerGroup input:checked').forEach(cb => {
            days.push(parseInt(cb.value));
        });
        data.recurrence_rule = {
            freq: document.getElementById('evRecFreq').value,
            days: days.length ? days : null,
            until: document.getElementById('evRecUntil').value || null,
        };
    }

    try {
        const url = isEdit
            ? `${API_BASE}/events/${currentEventId}${TEST_SUFFIX}`
            : `${API_BASE}/events${TEST_SUFFIX}`;

        const response = await fetch(url, {
            method: isEdit ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Save failed');
        }

        closeModal();
        calendar.refetchEvents();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

// ─── Delete Event ───
async function deleteEvent() {
    if (!currentEventId) return;
    if (!confirm('Delete this event?')) return;

    // Check if recurring
    const deleteChildren = confirm('Delete all recurring instances too?');

    try {
        const params = new URLSearchParams({ delete_children: deleteChildren });
        const response = await fetch(
            `${API_BASE}/events/${currentEventId}${TEST_SUFFIX}${TEST_SUFFIX ? '&' : '?'}${params.toString()}`,
            { method: 'DELETE' }
        );

        if (!response.ok) throw new Error('Delete failed');

        closeModal();
        closeDetailModal();
        calendar.refetchEvents();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

// ─── Event Detail Modal ───
function showEventDetail(fcEvent) {
    const props = fcEvent.extendedProps;

    document.getElementById('detailTitle').textContent = fcEvent.title;

    // Type badge
    const typeColor = EVENT_COLORS[props.event_type] || '#667eea';
    document.getElementById('detailType').innerHTML = `
        <span class="detail-label">Type</span>
        <span class="event-type-badge" style="background:${typeColor}20; color:${typeColor}">
            <span class="type-dot" style="background:${typeColor}"></span>
            ${EVENT_LABELS[props.event_type] || props.event_type}
        </span>
    `;

    // Time
    const startStr = fcEvent.start ? formatDatetime(fcEvent.start) : '';
    const endStr = fcEvent.end ? formatDatetime(fcEvent.end) : '';
    document.getElementById('detailTime').innerHTML = `
        <span class="detail-label">Time</span>
        <span class="detail-value">${startStr}${endStr ? ' ~ ' + endStr : ''}${fcEvent.allDay ? ' (All Day)' : ''}</span>
    `;

    // Location
    document.getElementById('detailLocation').innerHTML = props.location
        ? `<span class="detail-label">Location</span><span class="detail-value">${escapeHtml(props.location)}</span>`
        : '';

    // Coach
    document.getElementById('detailCoach').innerHTML = props.coach_name
        ? `<span class="detail-label">Coach</span><span class="detail-value">${escapeHtml(props.coach_name)}</span>`
        : '';

    // Visibility
    const visLabels = { club: 'Club (everyone)', coaches: 'Coaches only', personal: 'Personal' };
    document.getElementById('detailVisibility').innerHTML = `
        <span class="detail-label">Visibility</span>
        <span class="detail-value">${visLabels[props.visibility] || props.visibility}</span>
    `;

    // Description
    document.getElementById('detailDesc').innerHTML = props.description
        ? `<span class="detail-label">Details</span><span class="detail-value">${escapeHtml(props.description)}</span>`
        : '';

    // Participants (future)
    document.getElementById('detailParticipants').innerHTML = '';

    // Store for edit
    currentEventId = fcEvent.id;
    document.getElementById('detailModal').style.display = 'flex';
}

function closeDetailModal() {
    document.getElementById('detailModal').style.display = 'none';
}

function editFromDetail() {
    closeDetailModal();

    // Fetch full event data and open edit modal
    fetch(`${API_BASE}/events/${currentEventId}${TEST_SUFFIX}`)
        .then(r => r.json())
        .then(data => openEditModal(data))
        .catch(err => {
            console.error(err);
            alert('Failed to load event details');
        });
}

// ─── Helpers ───
function updateColorPreview() {
    const type = document.getElementById('evType').value;
    const defaultColor = EVENT_COLORS[type] || '#667eea';
    document.getElementById('evColor').value = defaultColor;
    document.getElementById('colorPreview').style.background = defaultColor;
}

function toggleAllDay() {
    const allDay = document.getElementById('evAllDay').checked;
    const startInput = document.getElementById('evStart');
    const endInput = document.getElementById('evEnd');

    if (allDay) {
        startInput.type = 'date';
        endInput.type = 'date';
        startInput.value = startInput.value.slice(0, 10);
        endInput.value = endInput.value.slice(0, 10);
    } else {
        startInput.type = 'datetime-local';
        endInput.type = 'datetime-local';
    }
}

function toggleRecurrence() {
    const show = document.getElementById('evRecurring').checked;
    document.getElementById('recurrenceOptions').style.display = show ? 'block' : 'none';
}

function toggleDayPicker() {
    const freq = document.getElementById('evRecFreq').value;
    document.getElementById('dayPickerGroup').style.display = freq === 'weekly' ? 'block' : 'none';
}

function formatLocalDatetime(d) {
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatDatetime(d) {
    if (!d) return '';
    const date = d instanceof Date ? d : new Date(d);
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const h = String(date.getHours()).padStart(2, '0');
    const min = String(date.getMinutes()).padStart(2, '0');
    return `${y}-${m}-${day} ${h}:${min}`;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
