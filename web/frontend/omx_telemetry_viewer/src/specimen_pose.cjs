function specimenPosition(pose, fallback, notBefore = 0) {
  if (notBefore > 0) {
    const timestamp=Date.parse(pose && pose.timestamp);
    if (!Number.isFinite(timestamp) || timestamp < notBefore) return [...fallback];
  }
  const world=pose && pose.schema==='specimen_pose.v1' && pose.position_isaac_world_mm;
  const values=world && [world.x,world.y,world.z];
  if (!values || !values.every(v=>typeof v==='number' && Number.isFinite(v))) return [...fallback];
  return values.map(v=>v/1000);
}
module.exports={specimenPosition};
