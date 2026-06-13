/**
 * HealthGMP chatbot logger — free, no GCP, logs to a normal Google Sheet.
 *
 * SETUP (≈2 minutes):
 *  1. Create a Google Sheet (sheets.new). This is where logs land.
 *  2. Extensions → Apps Script. Delete the placeholder, paste this whole file.
 *  3. Click Deploy → New deployment → type "Web app".
 *       - Description: HealthGMP logger
 *       - Execute as: Me
 *       - Who has access: Anyone
 *     Deploy, authorize, and COPY the Web app URL (ends in /exec).
 *  4. Paste that URL into LOG_WEBHOOK_URL in .streamlit/secrets.toml
 *     (and into Streamlit Cloud → app → Settings → Secrets for the hosted app).
 *
 * The app POSTs one JSON record per event. `payload.sheet` names the tab
 * ("conversations", "escalations", "feedback"); tabs and headers are created
 * automatically on first write.
 */
function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var sheetName = data.sheet || 'conversations';
    delete data.sheet;

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sh = ss.getSheetByName(sheetName) || ss.insertSheet(sheetName);

    var keys = Object.keys(data);
    if (sh.getLastRow() === 0) {
      sh.appendRow(keys); // header row, written once
    }
    sh.appendRow(keys.map(function (k) { return data[k]; }));

    return ContentService
      .createTextOutput(JSON.stringify({ ok: true }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: String(err) }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
