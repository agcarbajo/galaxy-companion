# Builds and unit-tests the Android Dualboot app.  amd64 on purpose: Google
# publishes aapt2 for Linux only on x86_64.
FROM --platform=linux/amd64 eclipse-temurin:17-jdk-jammy

ENV ANDROID_HOME=/opt/android-sdk \
    GRADLE_VERSION=8.10.2
RUN apt-get update && apt-get install -y --no-install-recommends unzip curl && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL -o /tmp/tools.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
 && mkdir -p $ANDROID_HOME/cmdline-tools && unzip -q /tmp/tools.zip -d $ANDROID_HOME/cmdline-tools \
 && mv $ANDROID_HOME/cmdline-tools/cmdline-tools $ANDROID_HOME/cmdline-tools/latest && rm /tmp/tools.zip
RUN yes | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --licenses >/dev/null \
 && $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager "platforms;android-35" "build-tools;35.0.0" >/dev/null
RUN curl -fsSL -o /tmp/gradle.zip https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip \
 && unzip -q /tmp/gradle.zip -d /opt && rm /tmp/gradle.zip
ENV PATH=/opt/gradle-${GRADLE_VERSION}/bin:$PATH
WORKDIR /src
