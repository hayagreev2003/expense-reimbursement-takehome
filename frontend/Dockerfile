FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# Next inlines NEXT_PUBLIC_* into the bundle at build time, so this has to be a build arg.
# It is the browser that calls the API, so the value must be the host and port the browser
# sees - not the compose service name, which only resolves inside the network.
ARG NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

COPY . .
RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "start"]
