import WaveSurfer from './vendor/wavesurfer.esm.js'
import RegionsPlugin from './vendor/regions.esm.js'
import TimelinePlugin from './vendor/timeline.esm.js'
import { UI_LANGUAGES, applyStatic, has, language, locale, num, problemText, setLanguage, t } from './i18n.js'

const $ = (selector) => document.querySelector(selector)
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const FRAGMENT_COLOR = 'rgba(90, 169, 255, 0.22)'
const HIT_COLOR = 'rgba(245, 197, 66, 0.32)'
// Te same wartości co MODELS i LANGUAGES w app.py; nazwy i opisy są w słownikach static/i18n.
const MODELS = ['large-v3-turbo', 'small', 'medium', 'large-v3']
const LANGUAGES = ['auto', 'en', 'pl', 'de', 'uk', 'ru', 'cs', 'sk', 'fr', 'es', 'it']

// Ustawienia trzyma serwer w data/ustawienia.json; tu ich kopia do bieżącej pracy.
let appSettings = { ui_language: 'en', model: 'large-v3-turbo', language: 'auto', follow: true }

const state = {
  openId: null,     // plik, który właśnie się otwiera lub jest otwarty
  file: null,       // meta otwartego pliku
  ws: null,
  regions: null,
  words: [],        // {w, s, e, p, n: tekst znormalizowany, el: <span>}
  segCount: 0,
  curWord: -1,
  job: null,        // ostatni stan transkrypcji otwartego pliku
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
      message = problemText((await res.json()).detail) || message
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

// Pasek stanu pamięta, jak zbudować swój tekst, żeby po zmianie języka wypisać go od nowa.
let statusText = () => ''

function setStatus(text, isError = false) {
  statusText = typeof text === 'function' ? text : () => text
  const el = $('#status')
  el.textContent = statusText()
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
    select.replaceChildren(new Option(files.length ? t('library.count', { n: files.length }) : t('library.empty'), ''))
    for (const f of files) {
      let note = ''
      if (f.status === 'error' || f.transcript.status === 'error') note = ` [${t('library.tag_error')}]`
      else if (f.status !== 'ready' || f.transcript.status !== 'done') note = ` [${t('library.tag_pending')}]`
      const length = f.duration ? ` (${fmt(f.duration)})` : ''
      select.append(new Option(f.name + length + note, f.id))
    }
    select.value = state.openId ?? ''
  } catch (err) {
    setStatus(t('library.error', { message: err.message }), true)
  }
}

// Okienko przed każdą transkrypcją: język nagrania i model dla tego jednego pliku. Język nagrania
// nie zależy od języka interfejsu; ustawienia podsuwają tylko wybór na start.
let resolveTranscription = null

function askTranscription(fileName, { again = false, model, language }) {
  const dialog = $('#transcribe-dialog')
  $('#transcribe-title').textContent = t(again ? 'dialog.heading_again' : 'dialog.heading_new')
  $('#transcribe-file').textContent = fileName
  $('#transcribe-language').value = language
  $('#transcribe-model').value = model
  dialog.returnValue = ''
  dialog.showModal()
  return new Promise((resolve) => { resolveTranscription = resolve })
}

// Plik trafia do aplikacji dopiero po wyborze języka nagrania.
async function addFile(file) {
  if (document.querySelector('dialog[open]')) return
  const choice = await askTranscription(file.name, { model: appSettings.model, language: appSettings.language })
  if (choice) upload(file, choice)
}

function upload(file, choice) {
  const params = new URLSearchParams(choice)
  const xhr = new XMLHttpRequest()
  xhr.open('PUT', `/api/files?${params}`)
  xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name))
  xhr.upload.onprogress = (event) => {
    if (!event.lengthComputable) return
    const pct = Math.round((event.loaded / event.total) * 100)
    setStatus(() => t('upload.progress', { name: file.name, pct }))
  }
  xhr.onload = () => {
    if (xhr.status !== 200) {
      let message = xhr.statusText
      try { message = problemText(JSON.parse(xhr.responseText).detail) || message } catch {}
      setStatus(t('upload.failed', { message }), true)
      return
    }
    const meta = JSON.parse(xhr.responseText)
    openFile(meta.id)
    refreshLibrary()
  }
  xhr.onerror = () => setStatus(() => t('upload.error'), true)
  setStatus(() => t('upload.sending', { name: file.name }))
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
      const name = meta.name
      if (meta.status === 'error') {
        const error = meta.error
        setStatus(() => `${name}: ${problemText(error)}`, true)
        return
      }
      setStatus(() => t('file.extracting', { name }))
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
  updatePlayButton(false)
  $('#workspace').hidden = true
  $('#empty').hidden = false
}

function showFile(meta) {
  $('#empty').hidden = true
  $('#workspace').hidden = false
  $('#file-name').textContent = meta.name
  const a = meta.audio
  const channels = a.channels === 1 ? t('file.mono') : a.channels === 2 ? t('file.stereo') : t('file.channels', { n: a.channels })
  const parts = [fmt(meta.duration), `${a.codec}, ${num(a.sample_rate / 1000)} kHz, ${channels}`]
  if (a.bits === 24) parts.push(t('file.bits24'))
  if (a.has_video) parts.push(t('file.from_video'))
  if (a.audio_tracks > 1) parts.push(t('file.track', { n: a.audio_tracks }))
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
  ws.on('play', () => updatePlayButton(true))
  ws.on('pause', () => updatePlayButton(false))
  ws.on('interaction', () => setActive(null))
  ws.on('error', (err) => setStatus(t('player.error', { message: err.message }), true))

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

function updatePlayButton(playing = state.ws?.isPlaying()) {
  $('#play').textContent = t(playing ? 'player.pause' : 'player.play')
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
  state.job = null
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
    $('#tr-status').textContent = t('transcript.read_error', { message: err.message })
  }
  state.pollTimer = setTimeout(() => pollTranscript(token), 1500)
}

// Nazwa języka nagrania; Whisper wykrywa też języki spoza listy w ustawieniach.
function languageName(code) {
  if (has(`languages.${code}`)) return t(`languages.${code}`)
  try {
    return new Intl.DisplayNames([locale()], { type: 'language' }).of(code) || code
  } catch {
    return code
  }
}

function showTranscriptStatus(job) {
  state.job = job
  let text = ''
  if (job.status === 'waiting') text = t('transcript.waiting')
  else if (job.status === 'queued') text = t('transcript.queued', { model: job.model })
  else if (job.status === 'running' && job.phase === 'model') text = t('transcript.loading', { model: job.model })
  else if (job.status === 'running') {
    text = t('transcript.running', { pct: Math.round((job.progress || 0) * 100), model: job.model })
  } else if (job.status === 'done') {
    text = t('transcript.done', {
      model: job.model,
      language: languageName(job.detected_language),
      duration: formatDuration(job.seconds),
      ratio: num(job.seconds / state.file.duration, 2),
    })
  } else if (job.status === 'error') text = t('transcript.failed', { message: problemText(job.error) })
  const el = $('#tr-status')
  el.textContent = text
  el.classList.toggle('error', job.status === 'error')
  $('#retranscribe').disabled = job.status !== 'done' && job.status !== 'error'
}

function confidenceTitle(p) {
  return t('transcript.confidence', { pct: Math.round(p * 100) })
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
      if (word.p < 0.5) span.title = confidenceTitle(word.p)
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
  if (appSettings.follow && state.ws.isPlaying()) scrollWordIntoView(words[idx].el)
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
  if (query && !state.hits.length) info = t(state.words.length ? 'search.none' : 'search.none_pending')
  else if (query) info = t('search.count', { n: state.hits.length })
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
    li.append(time, ctx, button('+', t('search.add'), () => addHitAsFragment(hit)))
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
    length.textContent = `${num(region.end - region.start, 1)} s`
    li.append(
      badge, range, length,
      button('▶', t('fragments.play', { n }), () => playRegion(region)),
      button('WAV', t('fragments.wav_title'), () => exportRegion(region, 'wav')),
      button(t('fragments.original'), t('fragments.original_title'),
        () => exportRegion(region, 'copy'), !state.file?.has_original),
      button('✕', t('fragments.remove'), () => region.remove()),
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
  setStatus(() => t('export.preparing'))
  try {
    const res = await api(`/api/files/${state.file.id}/export?${params}`)
    const name = fileNameFrom(res.headers.get('content-disposition')) || 'fragment'
    const url = URL.createObjectURL(await res.blob())
    const link = Object.assign(document.createElement('a'), { href: url, download: name })
    document.body.append(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 10_000)
    setStatus(() => t('export.done', { name }))
  } catch (err) {
    setStatus(t('export.failed', { message: err.message }), true)
  }
}

// ---------- zdarzenia interfejsu ----------

$('#file-input').addEventListener('change', (event) => {
  const file = event.target.files[0]
  if (file) addFile(file)
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
  if (file) addFile(file)
})

$('#library').addEventListener('change', (event) => {
  if (event.target.value) openFile(event.target.value)
})

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

$('#transcribe-dialog').addEventListener('close', () => {
  const start = $('#transcribe-dialog').returnValue === 'start'
  resolveTranscription?.(start ? { model: $('#transcribe-model').value, language: $('#transcribe-language').value } : null)
  resolveTranscription = null
})

// Ponowna transkrypcja zaczyna od tego, co ten plik miał wybrane ostatnio.
$('#retranscribe').addEventListener('click', async () => {
  const file = state.file
  if (!file) return
  const choice = await askTranscription(file.name, {
    again: true,
    model: state.job?.model || appSettings.model,
    language: state.job?.language || appSettings.language,
  })
  if (!choice || state.file !== file) return
  try {
    await api(`/api/files/${file.id}/transcribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(choice),
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
  if (!file || !confirm(t('library.delete_confirm', { name: file.name }))) return
  closeFile()
  history.replaceState(null, '', location.pathname)
  try {
    await api(`/api/files/${file.id}`, { method: 'DELETE' })
    setStatus(() => t('library.deleted', { name: file.name }))
  } catch (err) {
    setStatus(err.message, true)
  }
  refreshLibrary()
})

document.addEventListener('keydown', (event) => {
  if (event.ctrlKey && event.key === ',') {
    event.preventDefault()
    if (!document.querySelector('dialog[open]')) openSettings()
    return
  }
  if (!state.ws || document.querySelector('dialog[open]') || event.ctrlKey || event.metaKey || event.altKey) return
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
let lastUpdate = null  // ostatni stan z /api/update, do ponownego wypisania po zmianie języka
const formatDay = (value) => new Date(value).toLocaleDateString(locale())
const formatMoment = (value) => new Date(value).toLocaleString(locale(), { dateStyle: 'short', timeStyle: 'short' })

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

function updateText(u) {
  const r = u.release
  if (u.status === 'idle') return t(u.auto ? 'updates.idle_auto' : 'updates.idle_off')
  if (u.status === 'checking') return t('updates.checking')
  if (u.status === 'up_to_date') return t('updates.latest')
  if (u.status === 'failed') return t('updates.failed', { message: problemText(u.error) })
  if (!r) return ''
  if (u.status === 'available') {
    return r.published
      ? t('updates.available_date', { version: r.version, date: formatDay(r.published) })
      : t('updates.available', { version: r.version })
  }
  if (u.status === 'downloading') {
    return u.progress != null
      ? t('updates.downloading_pct', { version: r.version, pct: Math.round(u.progress * 100) })
      : t('updates.downloading', { version: r.version })
  }
  return u.status === 'ready' ? t('updates.ready', { version: r.version }) : ''
}

function renderUpdate(u) {
  lastUpdate = u
  const r = u.release
  $('#app-version').textContent = `v${u.current}`
  $('#settings-version').textContent = t('settings.version', { version: u.current })
  $('#current-version').textContent = u.current
  $('#update-site').href = u.site
  let text = updateText(u)
  if (u.last_check && (u.status === 'idle' || u.status === 'up_to_date')) {
    text += ` ${t('updates.last_check', { when: formatMoment(u.last_check * 1000) })}`
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
  if (r) pill.textContent = t(u.status === 'ready' ? 'updates.pill_ready' : 'updates.pill_available', { version: r.version })
  $('#update-dot').hidden = pill.hidden
  if (u.updated_from && !updatedShown) {
    updatedShown = true
    setStatus(() => t('updates.updated', { from: u.updated_from, to: u.current }))
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
  // przy otwartych ustawieniach albo trwającej pracy częściej, w tle raz na minutę (wynik sprawdzania automatycznego)
  updateTimer = setTimeout(refreshUpdate, busy ? 700 : $('#settings').open ? 5000 : 60_000)
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

$('#update-check').addEventListener('click', () => {
  $('#update-status').textContent = t('updates.checking')
  $('#update-status').classList.remove('error')
  updateAction('/api/update/check')
})
$('#update-download').addEventListener('click', () => updateAction('/api/update/download'))
$('#update-auto').addEventListener('change', (event) => updateAction('/api/update/settings', { auto: event.target.checked }))
$('#update-restart').addEventListener('click', async () => {
  $('#update-status').textContent = t('updates.restarting')
  try {
    await api('/api/update/restart', { method: 'POST' })
  } catch (err) {
    $('#update-status').textContent = err.message
  }
})

// ---------- ustawienia ----------

let storageInfo = null

function formatBytes(bytes) {
  return bytes >= 1e9 ? `${num(bytes / 1e9, 1)} GB` : `${Math.max(1, Math.round(bytes / 1e6))} MB`
}

function fillSelect(select, options) {
  const value = select.value
  select.replaceChildren(...options.map(([optionValue, label]) => new Option(label, optionValue)))
  if (value) select.value = value
}

function fillOptions() {
  const models = MODELS.map((name) => [name, t(`models.${name}`)])
  const languages = LANGUAGES.map((code) => [code, t(`languages.${code}`)])
  fillSelect($('#set-model'), models)
  fillSelect($('#transcribe-model'), models)
  fillSelect($('#set-language'), languages)
  fillSelect($('#transcribe-language'), languages)
}

function applySettings(settings) {
  appSettings = settings
  if (settings.ui_language !== language()) {
    setLanguage(settings.ui_language)
    rerender()
  }
}

async function loadSettings() {
  try {
    applySettings(await (await api('/api/settings')).json())
  } catch {}
  renderSettings()
}

async function saveSettings(changes) {
  try {
    const res = await api('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    })
    applySettings(await res.json())
  } catch (err) {
    setStatus(t('settings.error', { message: err.message }), true)
  }
  renderSettings()
}

function renderSettings() {
  $('#set-ui-language').value = language()
  $('#set-model').value = appSettings.model
  $('#set-language').value = appSettings.language
  $('#set-follow').checked = appSettings.follow
  let hint = t(`models.desc.${appSettings.model}`)
  if (storageInfo) {
    const downloaded = storageInfo.models.some((m) => m.name === appSettings.model)
    hint += ` ${t(downloaded ? 'models.downloaded' : 'models.not_downloaded')}`
  }
  $('#model-hint').textContent = hint
}

async function refreshStorage() {
  try {
    storageInfo = await (await api('/api/storage')).json()
  } catch (err) {
    $('#data-info').textContent = err.message
    return
  }
  renderStorage()
  renderSettings()
}

function renderStorage() {
  const s = storageInfo
  if (!s) return
  $('#data-info').textContent = t('data.summary', { files: t('data.files', { n: s.files }), size: formatBytes(s.data_bytes) })
  $('#data-path').textContent = s.data_dir
  $('#models-info').textContent = s.models.length
    ? t('data.models_total', { list: s.models.map((m) => `${m.name}: ${formatBytes(m.bytes)}`).join(', '), size: formatBytes(s.models_bytes) })
    : t('data.no_models')
  $('#models-path').textContent = s.models_dir
}

// Zmiana języka bez ponownego uruchomienia: teksty z index.html, listy wyboru i wszystko,
// co skrypt wypisał sam. Komunikaty błędów zostają w języku, w którym się pojawiły.
function rerender() {
  applyStatic()
  fillOptions()
  updatePlayButton()
  $('#status').textContent = statusText()
  refreshLibrary()
  if (state.file) showFile(state.file)
  if (state.job) showTranscriptStatus(state.job)
  for (const word of state.words) if (word.p < 0.5) word.el.title = confidenceTitle(word.p)
  renderHits()
  renderFragments()
  if (lastUpdate) renderUpdate(lastUpdate)
  renderStorage()
  renderSettings()
}

function showSection(name) {
  for (const button of document.querySelectorAll('.settings-nav [data-section]')) {
    button.classList.toggle('active', button.dataset.section === name)
  }
  for (const panel of document.querySelectorAll('.settings-body [data-panel]')) {
    panel.hidden = panel.dataset.panel !== name
  }
}

function openSettings(section = 'general') {
  renderSettings()
  showSection(section)
  if (!$('#settings').open) $('#settings').showModal()
  refreshUpdate()
  refreshStorage()
}

$('#settings-open').addEventListener('click', () => openSettings())
$('#settings-close').addEventListener('click', () => $('#settings').close())
$('#update-pill').addEventListener('click', () => openSettings('updates'))
for (const button of document.querySelectorAll('.settings-nav [data-section]')) {
  button.addEventListener('click', () => showSection(button.dataset.section))
}
$('#set-ui-language').addEventListener('change', (event) => saveSettings({ ui_language: event.target.value }))
$('#set-model').addEventListener('change', (event) => saveSettings({ model: event.target.value }))
$('#set-language').addEventListener('change', (event) => saveSettings({ language: event.target.value }))
$('#set-follow').addEventListener('change', (event) => saveSettings({ follow: event.target.checked }))
for (const button of document.querySelectorAll('[data-open]')) {
  button.addEventListener('click', async () => {
    try {
      await api('/api/open-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder: button.dataset.open }),
      })
    } catch (err) {
      setStatus(err.message, true)
    }
  })
}

// ---------- start ----------

// Język interfejsu serwer wpisuje do <html lang>, więc teksty są właściwe od pierwszej klatki;
// do tej chwili klasa `booting` ukrywa stronę.
setLanguage(document.documentElement.lang)
applyStatic()
fillOptions()
fillSelect($('#set-ui-language'), UI_LANGUAGES)
updatePlayButton(false)
document.documentElement.classList.remove('booting')
loadSettings()
refreshUpdate()
refreshLibrary()
const initialId = location.hash.slice(1)
if (/^[0-9a-f]{8}$/.test(initialId)) openFile(initialId)
