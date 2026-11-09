// Helper to manage session persistent UUID in sessionStorage
export function getSessionId() {
  let sessionId = sessionStorage.getItem('question_paper_session_id');
  if (!sessionId) {
    sessionId = 'session_' + Math.random().toString(36).substring(2, 9) + '_' + Date.now();
    sessionStorage.setItem('question_paper_session_id', sessionId);
  }
  return sessionId;
}
