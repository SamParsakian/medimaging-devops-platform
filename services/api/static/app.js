const studiesBody = document.getElementById("studies-body");
const detailSection = document.getElementById("study-detail");

function previewBadge(study) {
  return study.preview_object_path
    ? '<span class="badge available">available</span>'
    : '<span class="badge unavailable">not available</span>';
}

async function loadStudies() {
  const response = await fetch("/studies");
  const studies = await response.json();

  studiesBody.innerHTML = "";
  for (const study of studies) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${study.orthanc_study_id}</td>
      <td>${study.modality ?? ""}</td>
      <td>${study.study_date ?? ""}</td>
      <td>${study.patient_id ?? ""}</td>
      <td>${study.processing_status}</td>
      <td>${previewBadge(study)}</td>
    `;
    row.addEventListener("click", () => loadStudyDetail(study.orthanc_study_id));
    studiesBody.appendChild(row);
  }
}

async function loadStudyDetail(studyId) {
  const [study, previewInfo] = await Promise.all([
    fetch(`/studies/${studyId}`).then((r) => r.json()),
    fetch(`/studies/${studyId}/preview-info`).then((r) => r.json()),
  ]);

  const previewBlock = previewInfo.available
    ? `<img class="preview-image" src="/studies/${studyId}/preview-image" alt="Study preview" />`
    : `<p class="placeholder">No preview available for this study.</p>`;

  detailSection.innerHTML = `
    <h2>Study Detail</h2>
    <table class="detail-table">
      <tr><th>Orthanc Study ID</th><td>${study.orthanc_study_id}</td></tr>
      <tr><th>Study Instance UID</th><td class="mono">${study.study_instance_uid}</td></tr>
      <tr><th>Patient ID</th><td>${study.patient_id ?? ""}</td></tr>
      <tr><th>Modality</th><td>${study.modality ?? ""}</td></tr>
      <tr><th>Study Date</th><td>${study.study_date ?? ""}</td></tr>
      <tr><th>Study Description</th><td>${study.study_description ?? ""}</td></tr>
      <tr><th>Series / Instances</th><td>${study.series_count} / ${study.instance_count}</td></tr>
      <tr><th>Processing Status</th><td>${study.processing_status}</td></tr>
      <tr><th>MinIO Preview Path</th><td class="mono">${previewInfo.preview_object_path ?? "n/a"}</td></tr>
    </table>
    ${previewBlock}
  `;
}

loadStudies();
