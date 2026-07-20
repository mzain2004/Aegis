import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Activity, AlertTriangle, ArrowUpRight, Check, CheckCircle2, ChevronRight, Clock3, FileText, History, LayoutDashboard, LockKeyhole, Menu, RefreshCw, ShieldCheck, Terminal, X, XCircle } from 'lucide-react'
import './styles.css'

const demoPending = [
  { nonce: '7d22b8e1…', approval_id: 'APR-2048', tool: 'kubernetes', operation: 'delete deployment', namespace: 'payments-prod', resource: 'checkout-api', created_at: '2026-07-21T10:42:00Z', status: 'PENDING' },
  { nonce: '4be19a02…', approval_id: 'APR-2047', tool: 'kubernetes', operation: 'scale deployment', namespace: 'edge-services', resource: 'gateway', created_at: '2026-07-21T10:38:00Z', status: 'PENDING' },
  { nonce: 'd97c6f10…', approval_id: 'APR-2046', tool: 'kubernetes', operation: 'patch secret', namespace: 'identity', resource: 'oauth-config', created_at: '2026-07-21T10:16:00Z', status: 'PENDING' },
]
const demoHistory = [{ status: 'completed' }, { status: 'completed' }, { status: 'failed' }, { status: 'completed' }, { status: 'completed' }]

const api = async (path, options) => {
  const response = await fetch(`/api${path}`, options)
  if (!response.ok) throw new Error(`API ${response.status}`)
  return response.json()
}

function App() {
  const [section, setSection] = useState('Overview')
  const [pending, setPending] = useState(demoPending)
  const [history, setHistory] = useState(demoHistory)
  const [ready, setReady] = useState(true)
  const [selected, setSelected] = useState(demoPending[0])
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [p, h, health] = await Promise.all([api('/approve/pending'), api('/approve/history'), api('/ready')])
      setPending(p); setHistory(h); setReady(health.status === 'ready'); setSelected(p[0] || null); setNotice('Live API connected')
    } catch { setNotice('Demo data · connect the FastAPI service to load live requests') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const completed = history.filter((item) => item.status === 'completed').length
  const success = history.length ? Math.round((completed / history.length) * 100) : 0
  const approve = async () => {
    if (!selected) return
    try { await api('/approve/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nonce: selected.nonce, approval_id: selected.approval_id }) }); setNotice('Request approved and execution started'); setPending((items) => items.filter((item) => item.nonce !== selected.nonce)); setSelected(null) }
    catch { setNotice('Approval requires an authenticated operator in the FastAPI service') }
  }
  const title = section === 'Overview' ? 'Control room' : section
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><ShieldCheck size={20}/></div><span>AEGIS</span><small>CONTROL ROOM</small></div>
      <div className="nav-label">OPERATIONS</div>
      <Nav icon={<LayoutDashboard size={17}/>} label="Overview" active={section === 'Overview'} onClick={() => setSection('Overview')} />
      <Nav icon={<AlertTriangle size={17}/>} label="Pending approvals" count={pending.length} active={section === 'Pending approvals'} onClick={() => setSection('Pending approvals')} />
      <Nav icon={<History size={17}/>} label="Execution history" active={section === 'Execution history'} onClick={() => setSection('Execution history')} />
      <Nav icon={<FileText size={17}/>} label="Audit log" active={section === 'Audit log'} onClick={() => setSection('Audit log')} />
      <div className="sidebar-foot"><div className="operator-avatar">ZR</div><div><strong>Operator</strong><span>zain.r · admin</span></div><ChevronRight size={15}/></div>
    </aside>
    <main className="main"><header><button className="mobile-menu"><Menu size={20}/></button><div><p className="crumb">AEGIS / {section.toUpperCase()}</p><h1>{title}</h1></div><div className="header-actions"><div className="health"><span className={ready ? 'dot green' : 'dot red'}></span><span>{ready ? 'System healthy' : 'System degraded'}</span></div><button className="icon-btn" onClick={load} title="Refresh"><RefreshCw size={17} className={loading ? 'spin' : ''}/></button></div></header>
      <div className="content">
        {notice && <div className="notice"><Activity size={15}/>{notice}<button onClick={() => setNotice('')}><X size={14}/></button></div>}
        {section === 'Overview' || section === 'Pending approvals' ? <>
          <section className="intro"><div><p className="eyebrow">OPERATOR QUEUE</p><h2>Review suspended requests</h2><p className="muted">Mutating Kubernetes actions are held here until an authorized operator releases them.</p></div><div className="last-sync"><span className="dot cyan"></span>Live monitoring <span>·</span> just now</div></section>
          <section className="metrics"><Metric icon={<AlertTriangle size={18}/>} label="Awaiting approval" value={pending.length} accent="amber" detail="Requires review"/><Metric icon={<CheckCircle2 size={18}/>} label="Success rate" value={`${success}%`} accent="green" detail="Last 24 hours"/><Metric icon={<Terminal size={18}/>} label="Executions today" value={history.length} accent="blue" detail="Across all operators"/><Metric icon={<Clock3 size={18}/>} label="Avg. response" value="1.8m" accent="purple" detail="Approval latency"/></section>
          <section className="workspace"><div className="panel queue-panel"><div className="panel-head"><div><h3>Pending queue</h3><p>{pending.length} requests need your attention</p></div><button className="text-btn" onClick={() => setSection('Pending approvals')}>View all <ArrowUpRight size={15}/></button></div><div className="table-wrap"><table><thead><tr><th>REQUEST</th><th>RESOURCE</th><th>RISK</th><th>RECEIVED</th><th></th></tr></thead><tbody>{pending.map((item) => <tr key={item.nonce} className={selected?.nonce === item.nonce ? 'selected' : ''} onClick={() => setSelected(item)}><td><div className="request-cell"><span className="request-icon"><Terminal size={15}/></span><div><strong>{item.operation}</strong><span>{item.tool} · {item.approval_id}</span></div></div></td><td><strong>{item.resource}</strong><span className="subline">{item.namespace}</span></td><td><span className={`risk ${item.operation.includes('delete') ? 'critical' : 'high'}`}>{item.operation.includes('delete') ? 'CRITICAL' : 'HIGH'}</span></td><td className="time">{relative(item.created_at)}</td><td><ChevronRight size={17} className="chevron"/></td></tr>)}</tbody></table>{pending.length === 0 && <div className="empty"><CheckCircle2 size={24}/><strong>Queue is clear</strong><span>No suspended requests are waiting for approval.</span></div>}</div></div>
            {selected && <aside className="detail panel"><div className="detail-head"><div><p className="eyebrow">SELECTED REQUEST</p><h3>{selected.approval_id}</h3></div><button className="close" onClick={() => setSelected(null)}><X size={16}/></button></div><div className="detail-status"><span className="dot amber"></span><strong>Awaiting approval</strong><span>Expires in 4m</span></div><Detail label="Operation" value={selected.operation}/><Detail label="Target" value={`${selected.namespace} / ${selected.resource}`}/><Detail label="Tool" value={selected.tool}/><div className="payload"><div className="payload-head"><span>PAYLOAD PREVIEW</span><LockKeyhole size={13}/></div><code>{`{\n  "operation": "${selected.operation}",\n  "namespace": "${selected.namespace}",\n  "resource": "${selected.resource}"\n}`}</code></div><div className="detail-actions"><button className="approve" onClick={approve}><Check size={16}/> Approve request</button><button className="reject" onClick={() => setNotice('Reject flow is not exposed by the current API')}><XCircle size={16}/> Reject</button></div></aside>}
          </section>
        </> : <section className="panel empty-page"><FileText size={28}/><h2>{section}</h2><p className="muted">This view is wired to the Aegis API and ready for its live records.</p><button className="text-btn" onClick={load}>Refresh data <RefreshCw size={15}/></button></section>}
      </div>
    </main>
  </div>
}

function Nav({ icon, label, count, active, onClick }) { return <button className={`nav-item ${active ? 'active' : ''}`} onClick={onClick}>{icon}<span>{label}</span>{count > 0 && <b>{count}</b>}</button> }
function Metric({ icon, label, value, accent, detail }) { return <div className="metric"><div className={`metric-icon ${accent}`}>{icon}</div><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></div> }
function Detail({ label, value }) { return <div className="detail-row"><span>{label}</span><strong>{value}</strong></div> }
function relative(date) { const mins = Math.max(1, Math.round((Date.now() - new Date(date).getTime()) / 60000)); return mins < 60 ? `${mins}m ago` : `${Math.round(mins / 60)}h ago` }
createRoot(document.getElementById('root')).render(<App />)
