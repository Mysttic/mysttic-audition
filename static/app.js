import WaveSurfer from './vendor/wavesurfer.esm.js'
import RegionsPlugin from './vendor/regions.esm.js'
import TimelinePlugin from './vendor/timeline.esm.js'

const $ = (selector) => document.querySelector(selector)
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const FRAGMENT_COLOR = 'rgba(90, 169, 255, 0.22)'
const HIT_COLOR = 'rgba(245, 197, 66, 0.32)'
const LANG_NAMES = {
  pl: 'polski', en: 'angielski', de: 'niemiecki', uk: 'ukraiński', ru: 'rosyjski',
  cs: 'czeski', sk: 'słowacki', fr: 'francuski', es: 'hiszpański', it: 'włoski',
}

const state = {
  openId: null,     // plik, który właśnie się otwiera lub jest otwarty
  file: null,       // meta otwartego pliku
  ws: null,
  regions: null,
  words: [],        // {w, s, e, p, n: tekst znormalizowany, el: <span>}
  segCount: 0,
  curWord: -1,
  hits: [],         // {from, to}: indeksy w state.words
  hitIdx: -1,
  hitRegion: null,
  fragments: [],    // regiony wavesurfera w kolejności dodania
  active: null,     // fragment odtwarzany do końca lub w pętli
  token: 0,         // zmienia się przy zmianie pliku i unieważnia stare odpytywania
  pollTimer: null,
}

// ---------- pomocnicze ----------

async function api(path, options) {
  const res = await fetch(path, options)
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const detail = (await res.json()).detail
      if (typeof detail === 'string') message = detail
    } catch {}
    throw new Error(message)
  }
  return res
}

function fmt(seconds) {
  const tenths = Math.round(Math.max(0, seconds || 0) * 10)
  const h = Math.floor(tenths / 36000)
  const m = Math.floor(tenths / 600) % 60
  const s = ((tenths % 600) / 10).toFixed(1).padStart(4, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

function formatDuration(seconds) {
  const s = Math.round(seconds || 0)
  return s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`
}

function setStatus(message, isError = false) {
  const el = $('#status')
  el.textContent = message
  el.classList.toggle('error', isError)
}

function button(text, title, onClick, disabled = false) {
  const b = document.createElement('button')
  b.textContent = text
  b.title = title
  b.disabled = disabled
  b.addEventListener('click', (event) => {
    event.stopPropagation()
    onClick()
  })
  return b
}

// Wyszukiwanie ignoruje wielkość liter, ogonki i interpunkcję.
function norm(text) {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/ł/g, 'l')
    .replace(/[^\p{L}\p{N}]+/gu, '')
}

// Tryb luźny łapie odmianę: „umowa” pasuje do „umowy”, „umowie”, „umowami”, „kara” do „karę”.
function tokenMatches(word, query, exact) {
  if (word === query) return true
  if (exact) return false
  if (query.length >= 3 && word.startsWith(query)) return true
  let common = 0
  while (common < word.length && common < query.length && word[common] === query[common]) common++
  const queryTail = query.length - common
  const wordTail = word.length - common
  if (common >= 4) return queryTail <= 2 && wordTail <= 3
  return common === 3 && queryTail <= 1 && wordTail <= 1  // krótkie słowa różniące się końcówką
}

// ---------- biblioteka, wysyłanie, otwieranie ----------

async function refreshLibrary() {
  try {
    const files = await (await api('/api/files')).json()
    const select = $('#library')
    select.replaceChildren(new Option(files.length ? `Biblioteka (${files.length})` : 'Biblioteka jest pusta', ''))
    for (const f of files) {
      let note = ''
      if (f.status === 'error' || f.transcript.status === 'error') note = ' [błąd]'
      else if (f.status !== 'ready' || f.transcript.status !== 'done') note = ' [w toku]'
      const length = f.duration ? ` (${fmt(f.duration)})` : ''
      select.append(new Option(f.name + length + note, f.id))
    }
    select.value = state.openId ?? ''
  } catch (err) {
    setStatus(`Biblioteka: ${err.message}`, true)
  }
}

function upload(file) {
  const params = new URLSearchParams({ model: $('#model').value, language: $('#language').value })
  const xhr = new XMLHttpRequest()
  xhr.open('PUT', `/api/files?${params}`)
  xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name))
  xhr.upload.onprogress = (event) => {
    if (event.lengthComputable) setStatus(`Wysyłanie ${file.name}: ${Math.round((event.loaded / event.total) * 100)}%`)
  }
  xhr.onload = () => {
    if (xhr.status !== 200) {
      let message = xhr.statusText
      try { message = JSON.parse(xhr.responseText).detail || message } catch {}
      setStatus(`Nie udało się dodać pliku: ${message}`, true)
      return
    }
    const meta = JSON.parse(xhr.responseText)
    openFile(meta.id)
    refreshLibrary()
  }
  xhr.onerror = () => setStatus('Błąd wysyłania pliku do aplikacji.', true)
  setStatus(`Wysyłanie ${file.name}…`)
  xhr.send(file)
}

async function openFile(id) {
  closeFile()
  const token = state.token
  state.openId = id
  history.replaceState(null, '', `#${id}`)
  $('#library').value = id
  try {
    let meta
    for (;;) {
      meta = await (await api(`/api/files/${id}`)).json()
      if (token !== state.token) return
      if (meta.status === 'ready') break
      if (meta.status === 'error') throw new Error(`${meta.name}: ${meta.error}`)
      setStatus(`${meta.name}: wyciąganie dźwięku…`)
      await sleep(800)
    }
    const bytes = new Uint8Array(await (await api(`/api/files/${id}/peaks`)).arrayBuffer())
    if (token !== state.token) return
    const peaks = new Float32Array(bytes.length)
    for (let i = 0; i < bytes.length; i++) peaks[i] = bytes[i] / 255
    state.file = meta
    setStatus('')
    showFile(meta)
    createPlayer(meta, peaks)
    pollTranscript(token)
  } catch (err) {
    if (token === state.token) setStatus(err.message, true)
  }
}

function closeFile() {
  state.token++
  clearTimeout(state.pollTimer)
  state.ws?.destroy()
  Object.assign(state, {
    openId: null, file: null, ws: null, regions: null,
    hits: [], hitIdx: -1, hitRegion: null, fragments: [], active: null,
  })
  resetTranscript()
  $('#hits').replaceChildren()
  $('#hits-info').textContent = ''
  renderFragments()
  $('#workspace').hidden = true
  $('#empty').hidden = false
}

function showFile(meta) {
  $('#empty').hidden = true
  $('#workspace').hidden = false
  $('#file-name').textContent = meta.name
  const a = meta.audio
  const channels = a.channels === 1 ? 'mono' : a.channels === 2 ? 'stereo' : `${a.channels} kanałów`
  const parts = [fmt(meta.duration), `${a.codec}, ${a.sample_rate / 1000} kHz, ${channels}`]
  if (a.bits === 24) parts.push('24 bity')
  if (a.has_video) parts.push('dźwięk wyciągnięty z wideo')
  if (a.audio_tracks > 1) parts.push(`ścieżka 1 z ${a.audio_tracks}`)
  $('#file-info').textContent = parts.join(' · ')
}

// ---------- odtwarzacz ----------

function createPlayer(meta, peaks) {
  const regions = RegionsPlugin.create()
  const ws = WaveSurfer.create({
    container: '#waveform',
    height: 140,
    waveColor: '#4a6a99',
    progressColor: '#9ac4ff',
    cursorColor: '#ffffff',
    url: `/api/files/${meta.id}/audio`,
    peaks: [peaks],          // fala liczona na serwerze, przeglądarka nie dekoduje całego pliku
    duration: meta.duration,
    plugins: [regions, TimelinePlugin.create({ height: 18, style: 'color:#8b93a1;font-size:11px' })],
  })
  state.ws = ws
  state.regions = regions
  $('#zoom').value = 0
  $('#time').textContent = `${fmt(0)} / ${fmt(meta.duration)}`

  ws.on('timeupdate', onTime)
  ws.on('play', () => { $('#play').textContent = '❚❚ Pauza' })
  ws.on('pause', () => { $('#play').textContent = '▶ Odtwórz' })
  ws.on('interaction', () => setActive(null))
  ws.on('error', (err) => setStatus(`Odtwarzanie: ${err.message}`, true))

  regions.enableDragSelection({ color: FRAGMENT_COLOR })
  regions.on('region-created', (region) => {
    if (region.id === 'hit') return
    state.fragments.push(region)
    renderFragments()
  })
  regions.on('region-updated', (region) => {
    if (region.id !== 'hit') renderFragments()
  })
  regions.on('region-removed', (region) => {
    if (state.active === region) state.active = null
    const count = state.fragments.length
    state.fragments = state.fragments.filter((r) => r !== region)
    if (state.fragments.length !== count) renderFragments()
  })
  regions.on('region-clicked', (region, event) => {
    event.stopPropagation()
    playRegion(region)
  })
}

function onTime(time) {
  if (!state.file) return
  $('#time').textContent = `${fmt(time)} / ${fmt(state.file.duration)}`
  const region = state.active
  if (region && state.ws.isPlaying() && time >= region.end) {
    if ($('#loop').checked) state.ws.setTime(region.start)
    else {
      state.ws.pause()
      setActive(null)
    }
  }
  highlightWord(time)
}

function seekAndPlay(time) {
  setActive(null)
  state.ws.setTime(Math.max(0, time))
  state.ws.play()
}

function playRegion(region) {
  setActive(region)
  state.ws.setTime(region.start)
  state.ws.play()
}

function setActive(region) {
  if (state.active === region) return
  state.active = region
  renderFragments()
}

// ---------- transkrypcja ----------

function resetTranscript() {
  state.words = []
  state.segCount = 0
  state.curWord = -1
  state.hits = []
  state.hitIdx = -1
  $('#transcript').replaceChildren()
  $('#tr-status').textContent = ''
}

async function pollTranscript(token) {
  if (token !== state.token || !state.file) return
  try {
    const res = await api(`/api/files/${state.file.id}/transcript?since=${state.segCount}`)
    const data = await res.json()
    if (token !== state.token) return
    appendSegments(data.segments)
    showTranscriptStatus(data.transcript)
    if (data.transcript.status === 'done' || data.transcript.status === 'error') {
      refreshLibrary()
      return
    }
  } catch (err) {
    if (token !== state.token) return
    $('#tr-status').textContent = `Błąd odczytu transkrypcji: ${err.message}`
  }
  state.pollTimer = setTimeout(() => pollTranscript(token), 1500)
}

function showTranscriptStatus(t) {
  let text = ''
  if (t.status === 'waiting') text = 'Czeka na przygotowanie dźwięku…'
  else if (t.status === 'queued') text = `W kolejce, model ${t.model}…`
  else if (t.status === 'running' && t.phase === 'model') {
    text = `Ładowanie modelu ${t.model}. Za pierwszym razem model jest pobierany, to może potrwać kilka minut…`
  } else if (t.status === 'running') {
    text = `Transkrypcja ${Math.round((t.progress || 0) * 100)}%, model ${t.model}. Tekst pojawia się na bieżąco.`
  } else if (t.status === 'done') {
    const lang = LANG_NAMES[t.detected_language] || t.detected_language
    const ratio = (t.seconds / state.file.duration).toFixed(2).replace('.', ',')
    text = `Gotowe: model ${t.model}, język ${lang}, czas ${formatDuration(t.seconds)} (${ratio} × długość nagrania).`
  } else if (t.status === 'error') text = `Błąd transkrypcji: ${t.error}`
  const el = $('#tr-status')
  el.textContent = text
  el.classList.toggle('error', t.status === 'error')
  $('#retranscribe').disabled = t.status !== 'done' && t.status !== 'error'
}

function appendSegments(segments) {
  if (!segments.length) return
  const fragment = document.createDocumentFragment()
  for (const seg of segments) {
    const p = document.createElement('p')
    p.className = 'seg'
    const ts = document.createElement('span')
    ts.className = 'ts'
    ts.dataset.t = seg.start
    ts.textContent = fmt(seg.start)
    p.append(ts)
    for (const word of seg.words) {
      const lead = word.w.match(/^\s*/)[0]
      if (lead) p.append(lead)
      const span = document.createElement('span')
      span.className = word.p < 0.5 ? 'w unsure' : 'w'
      if (word.p < 0.5) span.title = `Pewność rozpoznania ${Math.round(word.p * 100)}%`
      span.textContent = word.w.slice(lead.length)
      span.dataset.i = state.words.length
      state.words.push({ ...word, n: norm(word.w), el: span })
      p.append(span)
    }
    fragment.append(p)
  }
  $('#transcript').append(fragment)
  state.segCount += segments.length
  if ($('#search').value.trim()) runSearch(false)
}

function highlightWord(time) {
  const words = state.words
  let lo = 0
  let hi = words.length - 1
  let idx = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (words[mid].s <= time) {
      idx = mid
      lo = mid + 1
    } else hi = mid - 1
  }
  if (idx >= 0 && time > words[idx].e + 1) idx = -1  // cisza między wypowiedziami
  if (idx === state.curWord) return
  if (state.curWord >= 0) words[state.curWord]?.el.classList.remove('cur')
  state.curWord = idx
  if (idx < 0) return
  words[idx].el.classList.add('cur')
  if ($('#follow').checked && state.ws.isPlaying()) scrollWordIntoView(words[idx].el)
}

function scrollWordIntoView(el, force = false) {
  const box = $('#transcript').getBoundingClientRect()
  const r = el.getBoundingClientRect()
  if (force || r.top < box.top + 24 || r.bottom > box.bottom - 24) {
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }
}

// ---------- wyszukiwanie ----------

function runSearch(resetIndex) {
  const words = state.words
  for (const hit of state.hits) for (let i = hit.from; i <= hit.to; i++) words[i]?.el.classList.remove('hit')
  const query = $('#search').value.split(/\s+/).map(norm).filter(Boolean)
  const exact = $('#exact').checked
  const indexed = []  // pomija „słowa” złożone z samej interpunkcji
  for (let i = 0; i < words.length; i++) if (words[i].n) indexed.push(i)
  const hits = []
  if (query.length) {
    outer: for (let k = 0; k + query.length <= indexed.length; k++) {
      for (let j = 0; j < query.length; j++) {
        if (!tokenMatches(words[indexed[k + j]].n, query[j], exact)) continue outer
      }
      hits.push({ from: indexed[k], to: indexed[k + query.length - 1] })
    }
  }
  state.hits = hits
  if (resetIndex) state.hitIdx = -1
  for (const hit of hits) for (let i = hit.from; i <= hit.to; i++) words[i].el.classList.add('hit')
  renderHits()
}

function renderHits() {
  const list = $('#hits')
  list.replaceChildren()
  const words = state.words
  const query = $('#search').value.trim()
  let info = ''
  if (query && !state.hits.length) info = state.words.length ? 'Brak wyników.' : 'Brak wyników (transkrypcja jeszcze trwa).'
  else if (query) info = `Wyników: ${state.hits.length}. Enter: następny, Shift+Enter: poprzedni.`
  $('#hits-info').textContent = info
  state.hits.slice(0, 500).forEach((hit, i) => {
    const li = document.createElement('li')
    if (i === state.hitIdx) li.className = 'active'
    const time = document.createElement('span')
    time.className = 'mono t'
    time.textContent = fmt(words[hit.from].s)
    const ctx = document.createElement('span')
    ctx.className = 'ctx'
    const a = Math.max(0, hit.from - 6)
    const b = Math.min(words.length - 1, hit.to + 6)
    if (a > 0) ctx.append('…')
    for (let k = a; k <= b; k++) {
      const text = words[k].w
      if (k < hit.from || k > hit.to) {
        ctx.append(text)
        continue
      }
      const lead = text.match(/^\s*/)[0]
      const mark = document.createElement('mark')
      mark.textContent = text.slice(lead.length)
      ctx.append(lead, mark)
    }
    if (b < words.length - 1) ctx.append('…')
    li.append(time, ctx, button('+', 'Dodaj jako fragment do porównania lub eksportu', () => addHitAsFragment(hit)))
    li.addEventListener('click', () => playHit(i))
    list.append(li)
  })
  list.querySelector('li.active')?.scrollIntoView({ block: 'nearest' })
}

function playHit(i) {
  const hit = state.hits[i]
  if (!hit || !state.ws) return
  state.hitIdx = i
  const start = state.words[hit.from].s
  const end = state.words[hit.to].e
  state.hitRegion?.remove()
  state.hitRegion = state.regions.addRegion({ id: 'hit', start, end, color: HIT_COLOR, drag: false, resize: false })
  renderHits()
  scrollWordIntoView(state.words[hit.from].el, true)
  seekAndPlay(start - 0.6)
}

function addHitAsFragment(hit) {
  const pad = 0.25
  state.regions.addRegion({
    start: Math.max(0, state.words[hit.from].s - pad),
    end: Math.min(state.file.duration, state.words[hit.to].e + pad),
    color: FRAGMENT_COLOR,
  })
}

// ---------- fragmenty ----------

function fragmentLabel(n) {
  const el = document.createElement('div')
  el.textContent = n
  el.style.cssText = 'display:inline-block;padding:1px 6px;border-radius:0 0 4px 0;background:rgba(0,0,0,.5);color:#fff;font:600 12px system-ui,sans-serif'
  return el
}

function renderFragments() {
  const list = $('#fragments')
  list.replaceChildren()
  state.fragments.forEach((region, i) => {
    const n = i + 1
    if (region.labelNo !== n) {
      region.labelNo = n
      region.setContent(fragmentLabel(n))
    }
    const li = document.createElement('li')
    if (region === state.active) li.className = 'active'
    const badge = document.createElement('b')
    badge.className = 'badge'
    badge.textContent = n
    const range = document.createElement('span')
    range.className = 'mono'
    range.textContent = `${fmt(region.start)} → ${fmt(region.end)}`
    const length = document.createElement('span')
    length.className = 'muted'
    length.textContent = `${(region.end - region.start).toFixed(1)} s`
    li.append(
      badge, range, length,
      button('▶', `Odtwórz (klawisz ${n})`, () => playRegion(region)),
      button('WAV', 'Pobierz fragment wycięty co do próbki, bez kompresji', () => exportRegion(region, 'wav')),
      button('Oryginał', 'Pobierz fragment w oryginalnym kodeku, bez ponownego kodowania (granice z dokładnością do ramki, ok. 20 do 30 ms)',
        () => exportRegion(region, 'copy'), !state.file?.has_original),
      button('✕', 'Usuń fragment', () => region.remove()),
    )
    list.append(li)
  })
  $('#fragments-empty').hidden = state.fragments.length > 0
}

function fileNameFrom(disposition) {
  if (!disposition) return null
  const encoded = /filename\*=utf-8''([^;]+)/i.exec(disposition)
  if (encoded) return decodeURIComponent(encoded[1])
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain ? plain[1] : null
}

async function exportRegion(region, mode) {
  const params = new URLSearchParams({ start: region.start.toFixed(3), end: region.end.toFixed(3), mode })
  setStatus('Przygotowywanie pliku…')
  try {
    const res = await api(`/api/files/${state.file.id}/export?${params}`)
    const name = fileNameFrom(res.headers.get('content-disposition')) || 'fragment'
    const url = URL.createObjectURL(await res.blob())
    const link = Object.assign(document.createElement('a'), { href: url, download: name })
    document.body.append(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 10_000)
    setStatus(`Eksport fragmentu: ${name}`)
  } catch (err) {
    setStatus(`Eksport: ${err.message}`, true)
  }
}

// ---------- zdarzenia interfejsu ----------

$('#file-input').addEventListener('change', (event) => {
  const file = event.target.files[0]
  if (file) upload(file)
  event.target.value = ''
})

let dragDepth = 0
window.addEventListener('dragenter', (event) => {
  if (!event.dataTransfer?.types.includes('Files')) return
  dragDepth++
  document.body.classList.add('dragging')
})
window.addEventListener('dragleave', () => {
  dragDepth = Math.max(0, dragDepth - 1)
  if (!dragDepth) document.body.classList.remove('dragging')
})
window.addEventListener('dragover', (event) => event.preventDefault())
window.addEventListener('drop', (event) => {
  event.preventDefault()
  dragDepth = 0
  document.body.classList.remove('dragging')
  const file = event.dataTransfer?.files?.[0]
  if (file) upload(file)
})

$('#library').addEventListener('change', (event) => {
  if (event.target.value) openFile(event.target.value)
})

for (const id of ['model', 'language']) {
  const select = $(`#${id}`)
  const saved = localStorage.getItem(`audition.${id}`)
  if (saved && [...select.options].some((o) => o.value === saved)) select.value = saved
  select.addEventListener('change', () => localStorage.setItem(`audition.${id}`, select.value))
}

$('#play').addEventListener('click', () => state.ws?.playPause())

$('#zoom').addEventListener('input', (event) => {
  const v = Number(event.target.value)
  state.ws?.zoom(v === 0 ? 0 : 2 * 200 ** (v / 100))  // 0 = całe nagranie, max 400 px/s
})

$('#transcript').addEventListener('click', (event) => {
  if (!state.ws || !window.getSelection().isCollapsed) return  // zaznaczanie tekstu nie odtwarza
  const word = event.target.closest('.w')
  const ts = event.target.closest('.ts')
  if (word) seekAndPlay(state.words[Number(word.dataset.i)].s - 0.1)
  else if (ts) seekAndPlay(Number(ts.dataset.t))
})

let searchTimer
$('#search').addEventListener('input', () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => runSearch(true), 200)
})
$('#search').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault()
    clearTimeout(searchTimer)
    if (state.hitIdx === -1 && !state.hits.length) runSearch(true)
    const count = state.hits.length
    if (count) playHit((state.hitIdx + (event.shiftKey ? -1 : 1) + count) % count)
  }
})
$('#exact').addEventListener('change', () => runSearch(true))

$('#retranscribe').addEventListener('click', async () => {
  const file = state.file
  if (!file) return
  try {
    await api(`/api/files/${file.id}/transcribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: $('#model').value, language: $('#language').value }),
    })
    clearTimeout(state.pollTimer)
    state.token++
    resetTranscript()
    renderHits()
    pollTranscript(state.token)
  } catch (err) {
    setStatus(err.message, true)
  }
})

$('#delete').addEventListener('click', async () => {
  const file = state.file
  if (!file || !confirm(`Usunąć „${file.name}” z biblioteki aplikacji? Oryginalny plik na dysku zostaje.`)) return
  closeFile()
  history.replaceState(null, '', location.pathname)
  try {
    await api(`/api/files/${file.id}`, { method: 'DELETE' })
    setStatus(`Usunięto z biblioteki: ${file.name}`)
  } catch (err) {
    setStatus(err.message, true)
  }
  refreshLibrary()
})

document.addEventListener('keydown', (event) => {
  if (!state.ws || $('#about').open || event.ctrlKey || event.metaKey || event.altKey) return
  if (event.target.matches('input[type=search], input[type=text], select, textarea')) return
  if (event.code === 'Space') {
    event.preventDefault()
    state.ws.playPause()
  } else if (/^[1-9]$/.test(event.key)) {
    const region = state.fragments[Number(event.key) - 1]
    if (region) playRegion(region)
  } else if (event.key === 'l' || event.key === 'L') {
    $('#loop').checked = !$('#loop').checked
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault()
    state.ws.skip(-2)
  } else if (event.key === 'ArrowRight') {
    event.preventDefault()
    state.ws.skip(2)
  }
})

// ---------- wersja i aktualizacje ----------

let updateTimer
let updatedShown = false
const formatDay = (value) => new Date(value).toLocaleDateString('pl-PL')
const formatMoment = (value) => new Date(value).toLocaleString('pl-PL', { dateStyle: 'short', timeStyle: 'short' })

// Sekcja CHANGELOG.md jako zwykły tekst: nagłówki, punkty i akapity, bez wstawiania HTML.
function renderNotes(container, text) {
  container.replaceChildren()
  for (const line of text.split('\n')) {
    const el = document.createElement('div')
    const heading = /^#{1,4}\s+(.*)$/.exec(line)
    const item = /^\s*[-*]\s+(.*)$/.exec(line)
    if (!line.trim()) el.className = 'notes-gap'
    else if (heading) el.className = 'notes-heading'
    else if (item) el.className = 'notes-item'
    const content = heading ? heading[1] : item ? `• ${item[1]}` : line
    el.textContent = content.replace(/\*\*(.+?)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1')
    container.append(el)
  }
}

function renderUpdate(u) {
  const r = u.release
  $('#app-version').textContent = `v${u.current}`
  $('#about-version').textContent = `Wersja ${u.current}`
  $('#update-site').href = u.site
  const texts = {
    idle: u.auto ? 'Aplikacja sama sprawdzi, czy jest nowsza wersja.' : 'Automatyczne sprawdzanie jest wyłączone.',
    checking: 'Sprawdzanie…',
    up_to_date: 'Masz najnowszą wersję.',
    available: r && `Dostępna jest wersja ${r.version}${r.published ? ` z ${formatDay(r.published)}` : ''}.`,
    downloading: r && `Pobieranie wersji ${r.version}${u.progress != null ? `: ${Math.round(u.progress * 100)}%` : '…'}`,
    ready: r && `Wersja ${r.version} jest pobrana i sprawdzona. Zainstaluje się przy następnym uruchomieniu.`,
    failed: `Nie udało się: ${u.error}`,
  }
  let text = texts[u.status] || ''
  if (u.last_check && (u.status === 'idle' || u.status === 'up_to_date')) {
    text += ` Ostatnie sprawdzenie: ${formatMoment(u.last_check * 1000)}.`
  }
  $('#update-status').textContent = text
  $('#update-status').classList.toggle('error', u.status === 'failed')
  const notes = $('#update-notes')
  notes.hidden = !(r?.notes && (u.status === 'available' || u.status === 'ready'))
  if (notes.hidden) notes.replaceChildren()
  else renderNotes(notes, r.notes)
  const progress = $('#update-progress')
  progress.hidden = u.status !== 'downloading'
  if (u.progress != null) progress.value = u.progress
  else progress.removeAttribute('value')
  $('#update-check').disabled = u.status === 'checking' || u.status === 'downloading'
  $('#update-download').hidden = u.status !== 'available'
  $('#update-restart').hidden = u.status !== 'ready'
  $('#update-auto').checked = u.auto
  const pill = $('#update-pill')
  pill.hidden = !r || !['available', 'downloading', 'ready'].includes(u.status)
  if (r) pill.textContent = u.status === 'ready' ? `Wersja ${r.version} gotowa do instalacji` : `Dostępna wersja ${r.version}`
  if (u.updated_from && !updatedShown) {
    updatedShown = true
    setStatus(`Zaktualizowano z wersji ${u.updated_from} do ${u.current}.`)
  }
}

async function refreshUpdate() {
  clearTimeout(updateTimer)
  let busy = false
  try {
    const u = await (await api('/api/update')).json()
    renderUpdate(u)
    busy = u.status === 'checking' || u.status === 'downloading'
  } catch {}
  // przy otwartym oknie albo trwającej pracy częściej, w tle raz na minutę (wynik sprawdzania automatycznego)
  updateTimer = setTimeout(refreshUpdate, busy ? 700 : $('#about').open ? 5000 : 60_000)
}

async function updateAction(path, body) {
  try {
    const res = await api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
    renderUpdate(await res.json())
  } catch (err) {
    $('#update-status').textContent = err.message
    $('#update-status').classList.add('error')
  }
  refreshUpdate()
}

function openAbout() {
  $('#about').showModal()
  refreshUpdate()
}

$('#about-open').addEventListener('click', openAbout)
$('#update-pill').addEventListener('click', openAbout)
$('#about-close').addEventListener('click', () => $('#about').close())
$('#update-check').addEventListener('click', () => {
  $('#update-status').textContent = 'Sprawdzanie…'
  $('#update-status').classList.remove('error')
  updateAction('/api/update/check')
})
$('#update-download').addEventListener('click', () => updateAction('/api/update/download'))
$('#update-auto').addEventListener('change', (event) => updateAction('/api/update/settings', { auto: event.target.checked }))
$('#update-restart').addEventListener('click', async () => {
  $('#update-status').textContent = 'Zamykanie i instalacja…'
  try {
    await api('/api/update/restart', { method: 'POST' })
  } catch (err) {
    $('#update-status').textContent = err.message
  }
})

// ---------- start ----------

refreshUpdate()
refreshLibrary()
const initialId = location.hash.slice(1)
if (/^[0-9a-f]{8}$/.test(initialId)) openFile(initialId)
