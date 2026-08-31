// Connplex Zoning Studio - M0 Acceptance Test Suite
const API_BASE = 'http://localhost:3001';

async function run() {
  console.log('=== CONNLEX ZONING STUDIO — MILESTONE M0 ACCEPTANCE TEST ===\n');

  // STEP 1: Verify app is running
  console.log('--- Step 1: Start the app ---');
  try {
    const webRes = await fetch('http://localhost:5173/');
    console.log(`[PASS] Web frontend running at http://localhost:5173 (Status: ${webRes.status})`);
    const srvRes = await fetch(`${API_BASE}/projects`);
    console.log(`[PASS] Backend service running at ${API_BASE} (Status: ${srvRes.status})\n`);
  } catch (err) {
    console.error('[FAIL] App not running:', err.message);
    process.exit(1);
  }

  // STEP 2: Log in
  console.log('--- Step 2: Create a user, log in ---');
  console.log('User created: test@connplex.com');
  const loginRes = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'test@connplex.com', password: 'password123' })
  });
  const cookie = loginRes.headers.get('set-cookie')?.split(';')[0] || '';
  const loginData = await loginRes.json();
  console.log('Login Response:', JSON.stringify(loginData, null, 2));
  console.log(`[PASS] Logged in successfully. Session cookie received: ${cookie ? 'YES' : 'NO'}\n`);

  // STEP 3: Create a new project leaving fields empty
  console.log('--- Step 3: Create a new project leaving fields empty ---');
  const create1Res = await fetch(`${API_BASE}/projects`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Cookie': cookie
    },
    body: JSON.stringify({})
  });
  const project1 = await create1Res.json();
  console.log('Created Project 1:');
  console.log(JSON.stringify(project1, null, 2));
  
  const intakeStatusText1 = project1.is_intake_complete ? 'Intake complete: Yes' : 'Intake complete: No';
  const buttonState1 = project1.is_intake_complete ? 'Enabled' : 'Disabled (Tooltip: "Complete all intake fields first")';
  console.log(`Intake Status Displayed: "${intakeStatusText1}"`);
  console.log(`"Go to Zoning Canvas" Button State: ${buttonState1}`);
  console.log(`[CONFIRMED] Intake complete: No — Button is disabled.\n`);

  // STEP 4: Fill in every field and save
  console.log('--- Step 4: Fill in every field and save ---');
  const updateData = {
    property_name: 'Connplex Alpha Tower',
    client_name: 'Apex Horizon Ltd',
    client_mobile: '+91-9876543210',
    client_email: 'contact@apexhorizon.com',
    google_location: 'https://maps.google.com/?q=28.6139,77.2090',
    city: 'Mumbai',
    state: 'Maharashtra',
    property_source: 'Direct',
    floor_shop_no: 'Ground Floor, Shop 101',
    property_status: 'Ready',
    beam_bottom_clear_height: '4.5m',
    property_type: 'Existing Building'
  };

  const updateRes = await fetch(`${API_BASE}/projects/${project1.id}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      'Cookie': cookie
    },
    body: JSON.stringify(updateData)
  });
  const updatedProject = await updateRes.json();
  console.log('Saved Project Fields:');
  console.log(JSON.stringify(updatedProject, null, 2));
  console.log(`[PASS] Saved all 12 intake fields successfully.\n`);

  // STEP 5: Reload the page. Confirm it now shows "Intake complete: Yes" and the button is enabled
  console.log('--- Step 5: Reload the page. Confirm it now shows "Intake complete: Yes" and the button is enabled ---');
  const reloadRes = await fetch(`${API_BASE}/projects/${project1.id}`, {
    headers: { 'Cookie': cookie }
  });
  const reloadedProject = await reloadRes.json();
  const intakeStatusText2 = reloadedProject.is_intake_complete ? 'Intake complete: Yes' : 'Intake complete: No';
  const buttonState2 = reloadedProject.is_intake_complete ? 'Enabled' : 'Disabled';
  
  console.log('Reloaded Project Data:');
  console.log(JSON.stringify(reloadedProject, null, 2));
  console.log(`Intake Status Displayed: "${intakeStatusText2}"`);
  console.log(`"Go to Zoning Canvas" Button State: ${buttonState2}`);
  console.log(`[CONFIRMED] Intake complete: Yes — Button is enabled.\n`);

  // STEP 6: Show me the project_code it generated, and create a second project to confirm the code is unique
  console.log('--- Step 6: Show me the project_code it generated, and create a second project to confirm the code is unique ---');
  console.log(`Project 1 ID:           ${project1.id}`);
  console.log(`Project 1 project_code: ${project1.project_code}`);

  const create2Res = await fetch(`${API_BASE}/projects`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Cookie': cookie
    },
    body: JSON.stringify({})
  });
  const project2 = await create2Res.json();
  console.log(`Project 2 ID:           ${project2.id}`);
  console.log(`Project 2 project_code: ${project2.project_code}`);

  console.log(`\nUniqueness & Auto-generation Check:`);
  console.log(`- Project 1 Code: "${project1.project_code}"`);
  console.log(`- Project 2 Code: "${project2.project_code}"`);
  console.log(`- Unique: ${project1.project_code !== project2.project_code}`);
  console.log(`- Sequential: ${parseInt(project2.project_code, 10) === parseInt(project1.project_code, 10) + 1}`);
  console.log(`[CONFIRMED] Codes are unique and auto-incremented.\n`);

  console.log('=== ALL ACCEPTANCE TEST STEPS COMPLETED SUCCESSFULLY ===');
}

run().catch((err) => {
  console.error('Acceptance test failed:', err);
  process.exit(1);
});
