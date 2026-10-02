/* Shared form/JSON state for the two continuous BO design variables. */
(function () {
  'use strict';
  const labels = {cell_size_mm: 'Cell size', wall_thickness_mm: 'Wall thickness'};

  function validate(space) {
    if (!space || typeof space !== 'object' || Array.isArray(space)) {
      throw new Error('Parameter space must be a JSON object.');
    }
    for (const [key, label] of Object.entries(labels)) {
      const bounds = space[key];
      if (!Array.isArray(bounds) || bounds.length !== 2 ||
          !bounds.every(value => typeof value === 'number' && Number.isFinite(value) && value > 0) ||
          bounds[0] >= bounds[1]) {
        throw new Error(`${label}: enter positive numeric bounds with Min < Max.`);
      }
    }
    return space;
  }

  function create({jsonInput, fields, error}) {
    let lastError = '';
    function status(message = '') {
      lastError = message;
      error.textContent = message;
      error.hidden = !message;
      for (const pair of Object.values(fields)) {
        for (const input of pair) input.setAttribute('aria-invalid', message ? 'true' : 'false');
      }
      jsonInput.setAttribute('aria-invalid', message ? 'true' : 'false');
    }
    function parse() {
      let space;
      try { space = JSON.parse(jsonInput.value); }
      catch (_) { throw new Error('Invalid Parameter Space JSON. Fix the JSON before editing bounds or saving.'); }
      if (!space || typeof space !== 'object' || Array.isArray(space)) {
        throw new Error('Parameter space must be a JSON object.');
      }
      return space;
    }
    function fromJson() {
      try {
        const space = parse();
        for (const [key, inputs] of Object.entries(fields)) {
          const bounds = space[key];
          inputs.forEach((input, index) => {
            const value = Array.isArray(bounds) && bounds.length === 2 ? bounds[index] : null;
            input.value = typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
          });
        }
        // Project both domains before validation, so repairing one invalid
        // endpoint cannot silently restore stale values in the other domain.
        validate(space);
        status();
      } catch (err) { status(err.message); }
    }
    function fromNumbers() {
      try {
        const space = parse(); // Never discard malformed JSON or advanced fields.
        for (const [key, inputs] of Object.entries(fields)) {
          space[key] = inputs.map(input => input.value.trim() === '' ? NaN : Number(input.value));
        }
        validate(space);
        jsonInput.value = JSON.stringify(space, null, 2);
        status();
      } catch (err) { status(err.message); }
    }
    jsonInput.addEventListener('input', fromJson);
    for (const inputs of Object.values(fields)) {
      inputs.forEach(input => input.addEventListener('input', fromNumbers));
    }
    return {
      load(space) { jsonInput.value = JSON.stringify(space, null, 2); fromJson(); },
      read() {
        if (lastError) throw new Error(lastError);
        return validate(parse());
      },
    };
  }
  window.BOParameterSpaceEditor = {create};
})();
