window.MOCK_DATA = {
  memories: [
    {
      _id: 'm1',
      content: 'July 2024 Unit 3 outage slipped 6 days after intake temperatures stayed high through July.',
      score: 0.87,
      location: { type: 'Point', coordinates: [-79.07, 43.81] },
      metadata: { status: 'active', temperature_celsius: 31, plant_id: 'unit-3' },
      plant_id: 'unit-3'
    },
    {
      _id: 'm2',
      content: '2025 intake chiller retrofit made July safe for a full outage window if the work starts before 10am.',
      score: 0.92,
      location: { type: 'Point', coordinates: [-79.08, 43.82] },
      metadata: { status: 'active', temperature_celsius: 25, plant_id: 'unit-3' },
      plant_id: 'unit-3'
    }
  ],
  heat_points: [
    [43.81, -79.07, 0.9],
    [43.82, -79.08, 0.7],
    [43.8, -79.06, 0.5]
  ]
};
