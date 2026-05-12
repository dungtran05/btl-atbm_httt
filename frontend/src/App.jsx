import { useEffect, useMemo, useState } from "react";
import { api } from "./api";

const today = new Date().toISOString().slice(0, 10);

function App() {
  const [user, setUser] = useState(null);
  const [chain, setChain] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const verifyId = useMemo(() => {
    const match = window.location.pathname.match(/^\/verify\/([^/]+)$/);
    return match ? decodeURIComponent(match[1]) : "";
  }, []);

  useEffect(() => {
    if (verifyId) { setLoading(false); return; }
    api.me()
      .then(({ user }) => { setUser(user); return refreshChain(); })
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, [verifyId]);

  async function refreshChain() {
    const data = await api.chain();
    setChain(data);
    return data;
  }

  async function handleLogin(event) {
    event.preventDefault();
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const data = await api.login({ username: form.get("username"), password: form.get("password") });
      setUser(data.user);
      await refreshChain();
    } catch (err) { setError(err.message); }
  }

  async function handleLogout() {
    await api.logout();
    setUser(null);
    setChain(null);
  }

  if (verifyId) return <PublicVerify certificateId={verifyId} />;
  if (loading) return <Shell user={user}><p className="panel">Đang tải...</p></Shell>;

  if (!user) {
    return (
      <Shell>
        <form className="auth-card" onSubmit={handleLogin}>
          <p className="eyebrow">An toàn thông tin</p>
          <h2>Đăng nhập</h2>
          {error && <p className="message error">{error}</p>}
          <label>Tên đăng nhập<input name="username" autoComplete="username" required /></label>
          <label>Mật khẩu<input name="password" type="password" autoComplete="current-password" required /></label>
          <button type="submit">Đăng nhập</button>
        </form>
      </Shell>
    );
  }

  return (
    <Shell user={user} onLogout={handleLogout}>
      {message && <p className="message success">{message}</p>}
      {error && <p className="message error">{error}</p>}
      <Hero chain={chain} user={user} />
      <section className="grid">
        {user.role === "issuer" ? (
          <IssuePanel
            onIssued={async (result) => {
              setMessage(`Đã cấp chứng chỉ ${result.certificate_id}`);
              setError("");
              await refreshChain();
              window.open(result.download_url, "_blank", "noopener,noreferrer");
            }}
            onError={setError}
          />
        ) : (
          <LockedPanel title="Cấp chứng chỉ" />
        )}
        {user.role === "verifier" ? <VerifyFilePanel onError={setError} /> : <LockedPanel title="Xác thực chứng chỉ" />}
      </section>
      {user.role === "admin" && <UsersPanel currentUser={user} onError={setError} />}
      <Blocks blocks={chain?.blocks || []} />
    </Shell>
  );
}

function Shell({ user, onLogout, children }) {
  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">An toàn thông tin</p>
          <h1>DocumentChain</h1>
        </div>
        <nav className="nav">
          {user && <span className="user-badge">{user.username} · {user.role}</span>}
          {user && <button className="link-button" onClick={onLogout}>Đăng xuất</button>}
        </nav>
      </header>
      <main className="shell">{children}</main>
    </>
  );
}

function Hero({ chain, user }) {
  return (
    <section className="hero">
      <div className="hero-copy">
        <p className="eyebrow">React + FastAPI</p>
        <h2>Xác thực chứng chỉ số</h2>
        <p>Issuer nhập thông tin, backend sinh PDF, hash SHA-256, ký RSA và lưu bằng chứng lên blockchain cục bộ.</p>
        {user?.role === "issuer" && user.organization_name && (
          <p className="muted">Đơn vị: <strong>{user.organization_name}</strong></p>
        )}
      </div>
      <div className={`status-card ${chain?.chain_valid ? "ok" : "bad"}`}>
        <span>Trạng thái chuỗi</span>
        <strong>{chain?.chain_valid ? "Hợp lệ" : "Có lỗi"}</strong>
        <small>{chain?.chain_message || "Chưa tải dữ liệu"}</small>
      </div>
    </section>
  );
}

function IssuePanel({ onIssued, onError }) {
  const [mode, setMode] = useState("generate");
  const [result, setResult] = useState(null);

  async function submit(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      let res;
      if (mode === "generate") {
        res = await api.issueCertificate({
          student_name: form.get("student_name"),
          student_id: form.get("student_id"),
          course_name: form.get("course_name"),
          issued_at: form.get("issued_at"),
        });
      } else {
        const file = form.get("certificate_file");
        if (!file) throw new Error("Vui lòng chọn file chứng chỉ");
        res = await api.uploadCertificate(file, {
          student_name: form.get("student_name"),
          student_id: form.get("student_id"),
          course_name: form.get("course_name"),
          issued_at: form.get("issued_at"),
        });
      }
      setResult(res);
    } catch (err) { onError(err.message); }
  }

  function handleDownload() {
    if (result) {
      window.open(result.download_url, "_blank", "noopener,noreferrer");
      onIssued(result);
      setResult(null);
    }
  }

  return (
    <div className="panel">
      <h3>Cấp chứng chỉ</h3>
      {result ? (
        <div>
          <p>Chứng chỉ đã được cấp với ID: {result.certificate_id}</p>
          <button onClick={handleDownload}>Tải về chứng chỉ</button>
          <button onClick={() => setResult(null)} style={{ marginLeft: "1rem" }}>Cấp chứng chỉ mới</button>
        </div>
      ) : (
        <form onSubmit={submit}>
          <div style={{ marginBottom: "1rem" }}>
            <label>
              <input type="radio" name="mode" value="generate" checked={mode === "generate"} onChange={(e) => setMode(e.target.value)} />
              {" "}Nhập thông tin và sinh chứng chỉ
            </label>
            <br />
            <label>
              <input type="radio" name="mode" value="upload" checked={mode === "upload"} onChange={(e) => setMode(e.target.value)} />
              {" "}Upload file chứng chỉ
            </label>
          </div>
          <label>Họ tên sinh viên<input name="student_name" required /></label>
          <label>Mã sinh viên<input name="student_id" required /></label>
          <label>Tên chứng chỉ / khóa học<input name="course_name" required /></label>
          <label>Ngày cấp<input name="issued_at" type="date" defaultValue={today} required /></label>
          {mode === "upload" && (
            <label>File chứng chỉ<input name="certificate_file" type="file" accept=".pdf" required /></label>
          )}
          <button type="submit">Cấp chứng chỉ</button>
        </form>
      )}
    </div>
  );
}

function VerifyFilePanel({ onError }) {
  const [result, setResult] = useState(null);
  async function submit(event) {
    event.preventDefault();
    const file = event.currentTarget.document.files[0];
    if (!file) return;
    try { setResult(await api.verifyFile(file)); }
    catch (err) { onError(err.message); }
  }
  return (
    <form className="panel" onSubmit={submit}>
      <h3>Xác thực chứng chỉ</h3>
      <label>Tệp cần kiểm tra<input name="document" type="file" required /></label>
      <button type="submit">Kiểm tra toàn vẹn</button>
      {result && <VerificationResult result={result} compact />}
    </form>
  );
}

function LockedPanel({ title }) {
  return (
    <section className="panel">
      <h3>{title}</h3>
      <p className="muted">Tài khoản này không có quyền thực hiện thao tác này.</p>
    </section>
  );
}

function UsersPanel({ currentUser, onError }) {
  const [data, setData] = useState({ users: [], roles: [] });
  const [newRole, setNewRole] = useState("verifier");

  useEffect(() => {
    api.users().then(setData).catch((err) => onError(err.message));
  }, []);

  async function submit(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api.createUser({
        username: form.get("username"),
        password: form.get("password"),
        role: form.get("role"),
        organization_name: form.get("organization_name") || "",
      });
      event.currentTarget.reset();
      setNewRole("verifier");
      setData(await api.users());
    } catch (err) { onError(err.message); }
  }

  return (
    <section className="admin-grid">
      <form className="panel" onSubmit={submit}>
        <h3>Tạo người dùng</h3>
        <label>Tên đăng nhập<input name="username" required /></label>
        <label>Mật khẩu<input name="password" type="password" required /></label>
        <label>Vai trò
          <select name="role" value={newRole} onChange={(e) => setNewRole(e.target.value)}>
            {data.roles.map((role) => <option key={role} value={role}>{role}</option>)}
          </select>
        </label>
        {newRole === "issuer" && (
          <label>
            Tên đơn vị
            <input name="organization_name" required placeholder="vd: Đại học Bách Khoa Hà Nội" />
          </label>
        )}
        <button type="submit">Tạo tài khoản</button>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th><th>Username</th><th>Role</th><th>Đơn vị</th><th>New password</th><th>Created</th><th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.users.map((item) => (
              <UserRow
                key={item.id}
                user={item}
                roles={data.roles}
                isCurrentUser={item.id === currentUser.id}
                onError={onError}
                onChanged={async () => setData(await api.users())}
              />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function UserRow({ user, roles, isCurrentUser, onChanged, onError }) {
  const [username, setUsername] = useState(user.username);
  const [role, setRole] = useState(user.role);
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState(user.organization_name || "");

  useEffect(() => {
    setUsername(user.username);
    setRole(user.role);
    setPassword("");
    setOrgName(user.organization_name || "");
  }, [user]);

  async function save() {
    try {
      await api.updateUser(user.id, { username, role, password, organization_name: orgName });
      await onChanged();
    } catch (err) { onError(err.message); }
  }

  async function remove() {
    if (!window.confirm(`Delete user ${user.username}?`)) return;
    try { await api.deleteUser(user.id); await onChanged(); }
    catch (err) { onError(err.message); }
  }

  return (
    <tr>
      <td>{user.id}</td>
      <td><input value={username} onChange={(e) => setUsername(e.target.value)} /></td>
      <td>
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          {roles.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </td>
      <td>
        {role === "issuer"
          ? <input value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Tên đơn vị" />
          : <span className="muted">—</span>}
      </td>
      <td><input value={password} onChange={(e) => setPassword(e.target.value)} type="password" placeholder="Leave blank" /></td>
      <td>{user.created_at}</td>
      <td className="row-actions">
        <button type="button" onClick={save}>Save</button>
        <button type="button" className="danger-button" onClick={remove} disabled={isCurrentUser}>Delete</button>
      </td>
    </tr>
  );
}

function Blocks({ blocks }) {
  return (
    <section className="chain">
      <div className="section-heading">
        <h3>Blockchain</h3>
        <span>{blocks.length} block</span>
      </div>
      <div className="blocks">
        {blocks.map((block) => (
          <article className="block" key={block.index}>
            <div className="block-head">
              <strong>#{block.index}</strong>
              <span>{block.owner}</span>
            </div>
            <p>{block.document_name}</p>
            {block.certificate_id && (
              <p className="muted">
                Certificate ID: <a href={`/verify/${block.certificate_id}`}>{block.certificate_id}</a>
              </p>
            )}
            {block.issuer_name && (
              <p className="muted">Đơn vị cấp: <strong>{block.issuer_name}</strong></p>
            )}
            <dl>
              <dt>Document hash</dt><dd>{block.document_hash}</dd>
              <dt>Previous hash</dt><dd>{block.previous_hash}</dd>
              <dt>Block hash</dt><dd>{block.hash}</dd>
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}

function PublicVerify({ certificateId }) {
  const [result, setResult] = useState(null);
  useEffect(() => {
    api.verifyCertificate(certificateId).then(setResult).catch((err) => {
      setResult({ status: "invalid", title: "Không xác thực được", detail: err.message });
    });
  }, [certificateId]);
  return (
    <Shell>
      <section className={`result ${result?.status || ""}`}>
        {!result ? <p>Đang xác thực...</p> : <VerificationResult result={result} />}
      </section>
    </Shell>
  );
}

function VerificationResult({ result, compact = false }) {
  const block = result.block;
  return (
    <div className={compact ? "compact-result" : ""}>
      <p className="eyebrow">Kết quả xác thực</p>
      <h2>{result.title}</h2>
      <p>{result.detail}</p>
      <dl>
        <dt>Hash tài liệu</dt><dd>{result.document_hash || "Không có"}</dd>
        <dt>Blockchain</dt><dd>{result.chain_message}</dd>
        {block && (
          <>
            <dt>Certificate ID</dt><dd>{block.certificate_id || "Không có"}</dd>
            {block.issuer_name && <><dt>Đơn vị cấp</dt><dd>{block.issuer_name}</dd></>}
            <dt>Block</dt><dd>#{block.index} - {block.document_name} - {block.owner}</dd>
            <dt>Chữ ký số</dt><dd>{result.signature_valid ? "Hợp lệ ✓" : "Không hợp lệ ✗"}</dd>
            {block.metadata && (
              <>
                <dt>Sinh viên</dt><dd>{block.metadata.student_name} - {block.metadata.student_id}</dd>
                <dt>Chứng chỉ</dt><dd>{block.metadata.course_name}</dd>
              </>
            )}
          </>
        )}
      </dl>
    </div>
  );
}

export default App;
