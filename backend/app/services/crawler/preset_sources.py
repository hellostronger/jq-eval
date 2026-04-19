# 预置新闻源配置
# 这些是常见的RSS源，可以作为系统初始化数据

PRESET_RSS_SOURCES = [
    # ==================== 科技类 ====================
    {
        "name": "InfoQ中文",
        "domain": "tech",
        "source_url": "https://www.infoq.cn/feed",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True, "content_format": "markdown"}
    },
    {
        "name": "开源中国",
        "domain": "tech",
        "source_url": "https://www.oschina.net/news/rss",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True, "content_format": "markdown"}
    },
    {
        "name": "CSDN资讯",
        "domain": "tech",
        "source_url": "https://www.csdn.net/rss.html",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True, "content_format": "markdown"}
    },
    {
        "name": "科技行者",
        "domain": "tech",
        "source_url": "https://www.techwalker.com/feed",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "TechCrunch",
        "domain": "tech",
        "source_url": "https://techcrunch.com/feed/",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Engadget中文",
        "domain": "tech",
        "source_url": "https://cn.engadget.com/rss.xml",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Wired",
        "domain": "tech",
        "source_url": "https://www.wired.com/feed/rss",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "The Verge",
        "domain": "tech",
        "source_url": "https://www.theverge.com/rss/index.xml",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },

    # ==================== 财经类 ====================
    {
        "name": "东方财富网",
        "domain": "finance",
        "source_url": "https://www.eastmoney.com/rss.html",
        "source_type": "rss",
        "crawl_frequency": "30 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "雪球热门",
        "domain": "finance",
        "source_url": "https://xueqiu.com/hots/topic/rss",
        "source_type": "rss",
        "crawl_frequency": "30 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "财新网",
        "domain": "finance",
        "source_url": "https://www.caixin.com/rss.html",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Bloomberg",
        "domain": "finance",
        "source_url": "https://www.bloomberg.com/feed/podcast/bloomberg-technology.xml",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Reuters Business",
        "domain": "finance",
        "source_url": "https://www.reutersagency.com/feed/?tax=business-finance",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },

    # ==================== 综合新闻 ====================
    {
        "name": "新华网",
        "domain": "news",
        "source_url": "http://www.news.cn/rss.html",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "BBC News",
        "domain": "news",
        "source_url": "https://feeds.bbci.co.uk/news/rss.xml",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "CNN",
        "domain": "news",
        "source_url": "http://rss.cnn.com/rss/edition.rss",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Reuters World",
        "domain": "news",
        "source_url": "https://www.reutersagency.com/feed/?tax=world-news",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "NYTimes World",
        "domain": "news",
        "source_url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "澎湃新闻",
        "domain": "news",
        "source_url": "https://www.thepaper.cn/rss.html",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },

    # ==================== 体育类 ====================
    {
        "name": "ESPN",
        "domain": "sports",
        "source_url": "https://www.espn.com/espn/rss/news",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "体育画报",
        "domain": "sports",
        "source_url": "https://www.si.com/rss/si_topstories.rss",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Bleacher Report",
        "domain": "sports",
        "source_url": "https://bleacherreport.com/articles/feed",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "NBA官网",
        "domain": "sports",
        "source_url": "https://www.nba.com/rss/nba_rss.xml",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "虎扑体育",
        "domain": "sports",
        "source_url": "https://www.hupu.com/rss",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },

    # ==================== 健康类 ====================
    {
        "name": "WebMD",
        "domain": "health",
        "source_url": "https://rssfeeds.webmd.com/rss/rss.aspx?RSSSource=RSSConsumer",
        "source_type": "rss",
        "crawl_frequency": "0 */2 * * *",  # 每2小时
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Healthline",
        "domain": "health",
        "source_url": "https://www.healthline.com/rss.xml",
        "source_type": "rss",
        "crawl_frequency": "0 */2 * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Mayo Clinic",
        "domain": "health",
        "source_url": "https://news.mayoclinic.org/feed/",
        "source_type": "rss",
        "crawl_frequency": "0 */2 * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "丁香园",
        "domain": "health",
        "source_url": "https://www.dxy.cn/rss",
        "source_type": "rss",
        "crawl_frequency": "0 */2 * * *",
        "crawl_config": {"fetch_full_content": True}
    },

    # ==================== 教育类 ====================
    {
        "name": "中国教育报",
        "domain": "education",
        "source_url": "https://www.jyb.cn/rss.html",
        "source_type": "rss",
        "crawl_frequency": "0 */2 * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "芥末堆",
        "domain": "education",
        "source_url": "https://www.jiemodui.com/rss",
        "source_type": "rss",
        "crawl_frequency": "0 */2 * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Education Week",
        "domain": "education",
        "source_url": "https://www.edweek.org/feed",
        "source_type": "rss",
        "crawl_frequency": "0 */2 * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Chronicle Higher Ed",
        "domain": "education",
        "source_url": "https://www.chronicle.com/rss",
        "source_type": "rss",
        "crawl_frequency": "0 */2 * * *",
        "crawl_config": {"fetch_full_content": True}
    },

    # ==================== 科学类 ====================
    {
        "name": "ScienceDaily",
        "domain": "science",
        "source_url": "https://www.sciencedaily.com/rss/all.xml",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Nature",
        "domain": "science",
        "source_url": "https://www.nature.com/nature.rss",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Scientific American",
        "domain": "science",
        "source_url": "https://www.scientificamerican.com/rss/",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "NASA News",
        "domain": "science",
        "source_url": "https://www.nasa.gov/rss/dyn/breaking_news.rss",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },

    # ==================== 娱乐类 ====================
    {
        "name": "Variety",
        "domain": "entertainment",
        "source_url": "https://variety.com/feed/",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Entertainment Weekly",
        "domain": "entertainment",
        "source_url": "https://ew.com/feed/",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": "Rolling Stone",
        "domain": "entertainment",
        "source_url": "https://www.rollingstone.com/feed/",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },

    # ==================== 生活类 ====================
    {
        "name": "Lifehacker",
        "domain": "lifestyle",
        "source_url": "https://lifehacker.com/rss",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
    {
        "name": " Apartment Therapy",
        "domain": "lifestyle",
        "source_url": "https://www.apartmenttherapy.com/feed",
        "source_type": "rss",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {"fetch_full_content": True}
    },
]

# 网页爬取配置模板（需要用户根据实际网站调整）
PRESET_WEB_SOURCE_TEMPLATES = [
    {
        "name": "36氪（需配置）",
        "domain": "tech",
        "source_url": "https://36kr.com/news",
        "source_type": "web",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {
            "article_list_selector": ".article-item, .news-item",
            "selectors": {
                "title": "h1, h2, .title",
                "link": "a",
                "content": ".content, .article-content",
                "author": ".author, .name",
                "time": "time, .date",
            },
            "fetch_full_content": True,
            "max_articles": 20
        }
    },
    {
        "name": "虎嗅（需配置）",
        "domain": "tech",
        "source_url": "https://www.huxiu.com",
        "source_type": "web",
        "crawl_frequency": "0 * * * *",
        "crawl_config": {
            "article_list_selector": ".article-item, article",
            "selectors": {
                "title": "h1, h2, .title",
                "link": "a",
                "content": ".article-content, .content",
            },
            "fetch_full_content": True,
            "max_articles": 20
        }
    },
]


async def init_preset_sources(db):
    """初始化预置新闻源"""
    from app.models.hot_news import HotNewsSource
    from sqlalchemy import select

    for source_data in PRESET_RSS_SOURCES:
        # 检查是否已存在
        result = await db.execute(
            select(HotNewsSource).where(HotNewsSource.name == source_data["name"])
        )
        if result.scalar_one_or_none():
            continue

        source = HotNewsSource(
            name=source_data["name"],
            domain=source_data["domain"],
            source_url=source_data["source_url"],
            source_type=source_data["source_type"],
            crawl_frequency=source_data["crawl_frequency"],
            crawl_config=source_data.get("crawl_config", {}),
            is_active=True,
            is_builtin=True  # 内置源标记
        )
        db.add(source)

    await db.commit()
    print("[OK] 预置RSS新闻源已初始化")


# 需要在HotNewsSource模型中添加is_builtin字段
# is_builtin = Column(Boolean, default=False)