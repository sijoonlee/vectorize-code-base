export const requireAuth = (request) => {
  if (!request.user) {
    throw new Error("Unauthorized");
  }

  return request.user;
};
